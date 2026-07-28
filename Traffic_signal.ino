/*
 * AI Traffic Management System - ESP32 signal gateway
 * =====================================================================
 *
 * Receives phase commands from the backend's hardware bridge and drives twelve
 * LEDs (four approaches x red/yellow/green).
 *
 * Set TRAFFIC_HARDWARE_WEBHOOK_URL on the backend to this device:
 *
 *     TRAFFIC_HARDWARE_WEBHOOK_URL=http://<device-ip>/signals
 *     TRAFFIC_HARDWARE_WEBHOOK_TOKEN=<the SHARED_TOKEN below>
 *
 * The sketch accepts either the JSON body or its "compact" field, e.g.
 *
 *     E:R28,N:G28,S:G28,W:R28
 *
 * FAILSAFE
 * --------
 * If no valid command arrives for COMMAND_TIMEOUT_MS the sketch drops every
 * approach to flashing amber. It also starts in flashing amber after a reset,
 * and refuses any command that would show conflicting greens.
 *
 * This is a bench and simulation aid. Signals on a public road are
 * safety-critical: they require an independent hardware conflict monitor and
 * approval from the responsible road authority. See docs/hardware.md.
 *
 * Simulate it in a browser first: https://wokwi.com/
 */

#include <WiFi.h>
#include <WebServer.h>

// ---------------------------------------------------------------- config ---
const char *WIFI_SSID = "your-network";
const char *WIFI_PASSWORD = "your-password";

// Must match TRAFFIC_HARDWARE_WEBHOOK_TOKEN. Empty disables the check.
const char *SHARED_TOKEN = "";

// Fall back to flashing amber when the backend goes quiet for this long.
const unsigned long COMMAND_TIMEOUT_MS = 10000;
const unsigned long FLASH_INTERVAL_MS = 500;

// ------------------------------------------------------------------ pins ---
enum Approach { NORTH = 0, SOUTH = 1, EAST = 2, WEST = 3, APPROACH_COUNT = 4 };
enum Lamp { RED = 0, YELLOW = 1, GREEN = 2, LAMP_COUNT = 3 };

// [approach][lamp]
const uint8_t SIGNAL_PINS[APPROACH_COUNT][LAMP_COUNT] = {
    {16, 17, 18},  // north
    {19, 21, 22},  // south
    {23, 25, 26},  // east
    {27, 32, 33},  // west
};

// A pedestrian push-button, wired to ground with the internal pull-up.
const uint8_t PEDESTRIAN_BUTTON_PIN = 4;

// ----------------------------------------------------------------- state ---
char currentAspect[APPROACH_COUNT];  // 'R', 'Y', 'G' or 'F' (flashing amber)
unsigned long lastCommandAt = 0;
bool inFailsafe = true;
bool flashOn = false;
unsigned long lastFlashToggle = 0;
unsigned long commandsAccepted = 0;
unsigned long commandsRejected = 0;

WebServer server(80);

// ------------------------------------------------------------ lamp output ---
void writeLamps(Approach approach, bool red, bool yellow, bool green) {
  digitalWrite(SIGNAL_PINS[approach][RED], red ? HIGH : LOW);
  digitalWrite(SIGNAL_PINS[approach][YELLOW], yellow ? HIGH : LOW);
  digitalWrite(SIGNAL_PINS[approach][GREEN], green ? HIGH : LOW);
}

void applyAspect(Approach approach, char aspect) {
  switch (aspect) {
    case 'G': writeLamps(approach, false, false, true);  break;
    case 'Y': writeLamps(approach, false, true,  false); break;
    case 'R': writeLamps(approach, true,  false, false); break;
    default:  writeLamps(approach, false, false, false); break;
  }
}

void enterFailsafe(const char *reason) {
  if (!inFailsafe) {
    Serial.print("FAILSAFE: ");
    Serial.println(reason);
  }
  inFailsafe = true;
  for (int i = 0; i < APPROACH_COUNT; i++) {
    currentAspect[i] = 'F';
  }
}

/* Flash every amber together while in failsafe. */
void serviceFailsafeFlash() {
  unsigned long now = millis();
  if (now - lastFlashToggle < FLASH_INTERVAL_MS) {
    return;
  }
  lastFlashToggle = now;
  flashOn = !flashOn;

  for (int i = 0; i < APPROACH_COUNT; i++) {
    writeLamps((Approach)i, false, flashOn, false);
  }
}

// ----------------------------------------------------------- safety check ---
/*
 * Refuse any command that would put a north/south green up at the same time as
 * an east/west green. The backend's phase machine should never send one, but a
 * device driving real lamps must not take that on trust.
 */
bool hasConflictingGreens(const char aspects[APPROACH_COUNT]) {
  bool northSouthGreen = aspects[NORTH] == 'G' || aspects[SOUTH] == 'G';
  bool eastWestGreen = aspects[EAST] == 'G' || aspects[WEST] == 'G';
  return northSouthGreen && eastWestGreen;
}

// -------------------------------------------------------------- parsing ----
int approachFromLetter(char letter) {
  switch (letter) {
    case 'N': return NORTH;
    case 'S': return SOUTH;
    case 'E': return EAST;
    case 'W': return WEST;
    default:  return -1;
  }
}

/*
 * Parse "E:R28,N:G28,S:G28,W:R28" into per-approach aspects.
 * Returns false when the string is malformed or incomplete.
 */
bool parseCompactCommand(const String &payload, char aspects[APPROACH_COUNT]) {
  bool seen[APPROACH_COUNT] = {false, false, false, false};
  int index = 0;

  while (index < (int)payload.length()) {
    int separator = payload.indexOf(',', index);
    if (separator < 0) {
      separator = payload.length();
    }

    String token = payload.substring(index, separator);
    token.trim();
    index = separator + 1;

    int colon = token.indexOf(':');
    if (colon < 1 || colon + 1 >= (int)token.length()) {
      continue;
    }

    int approach = approachFromLetter(token.charAt(0));
    char aspect = token.charAt(colon + 1);
    if (approach < 0) {
      continue;
    }
    // 'F' from the wire means flashing; treat it as failsafe amber.
    if (aspect != 'R' && aspect != 'Y' && aspect != 'G' && aspect != 'F' && aspect != 'O') {
      continue;
    }

    aspects[approach] = aspect;
    seen[approach] = true;
  }

  for (int i = 0; i < APPROACH_COUNT; i++) {
    if (!seen[i]) {
      return false;
    }
  }
  return true;
}

/* Pull the "compact" value out of the JSON body without a JSON parser. */
bool extractCompactField(const String &body, String &out) {
  int key = body.indexOf("\"compact\"");
  if (key < 0) {
    return false;
  }
  int start = body.indexOf('"', body.indexOf(':', key) + 1);
  int end = body.indexOf('"', start + 1);
  if (start < 0 || end < 0) {
    return false;
  }
  out = body.substring(start + 1, end);
  return true;
}

// ------------------------------------------------------------- endpoints ---
bool authorised() {
  if (strlen(SHARED_TOKEN) == 0) {
    return true;
  }
  String header = server.header("Authorization");
  return header == String("Bearer ") + SHARED_TOKEN;
}

void handleSignals() {
  if (!authorised()) {
    commandsRejected++;
    server.send(401, "text/plain", "unauthorised");
    return;
  }

  String body = server.arg("plain");
  String compact;
  if (!extractCompactField(body, compact)) {
    compact = body;  // allow the bare compact form too
  }

  char aspects[APPROACH_COUNT] = {'R', 'R', 'R', 'R'};
  if (!parseCompactCommand(compact, aspects)) {
    commandsRejected++;
    server.send(400, "text/plain", "malformed command");
    // Deliberately keep the last valid state: one bad packet is not a reason
    // to disrupt a running intersection. The watchdog still applies.
    return;
  }

  if (hasConflictingGreens(aspects)) {
    commandsRejected++;
    enterFailsafe("conflicting greens requested");
    server.send(409, "text/plain", "conflicting greens refused");
    return;
  }

  for (int i = 0; i < APPROACH_COUNT; i++) {
    currentAspect[i] = aspects[i];
    applyAspect((Approach)i, aspects[i]);
  }

  inFailsafe = false;
  lastCommandAt = millis();
  commandsAccepted++;
  server.send(200, "application/json", "{\"status\":\"applied\"}");
}

void handleStatus() {
  String body = "{\"failsafe\":";
  body += inFailsafe ? "true" : "false";
  body += ",\"accepted\":";
  body += commandsAccepted;
  body += ",\"rejected\":";
  body += commandsRejected;
  body += ",\"aspects\":\"";
  for (int i = 0; i < APPROACH_COUNT; i++) {
    body += currentAspect[i];
  }
  body += "\"}";
  server.send(200, "application/json", body);
}

// ------------------------------------------------------------- lifecycle ---
void setup() {
  Serial.begin(115200);

  for (int approach = 0; approach < APPROACH_COUNT; approach++) {
    for (int lamp = 0; lamp < LAMP_COUNT; lamp++) {
      pinMode(SIGNAL_PINS[approach][lamp], OUTPUT);
      digitalWrite(SIGNAL_PINS[approach][lamp], LOW);
    }
  }
  pinMode(PEDESTRIAN_BUTTON_PIN, INPUT_PULLUP);

  // Start safe: flashing amber until the backend says otherwise.
  enterFailsafe("power-on");

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 30000) {
    serviceFailsafeFlash();
    delay(50);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("\nReady at http://");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWiFi unavailable; holding failsafe");
  }

  const char *headerKeys[] = {"Authorization"};
  server.collectHeaders(headerKeys, 1);

  server.on("/signals", HTTP_POST, handleSignals);
  server.on("/status", HTTP_GET, handleStatus);
  server.begin();
}

void loop() {
  server.handleClient();

  // Watchdog: the backend has gone quiet, so stop trusting the last command.
  if (!inFailsafe && millis() - lastCommandAt > COMMAND_TIMEOUT_MS) {
    enterFailsafe("no command received within the timeout");
  }

  if (inFailsafe) {
    serviceFailsafeFlash();
  }

  // A pressed button is reported to the backend, which decides when to serve
  // the crossing -- the gateway never changes the signals on its own.
  static bool previouslyPressed = false;
  bool pressed = digitalRead(PEDESTRIAN_BUTTON_PIN) == LOW;
  if (pressed && !previouslyPressed) {
    Serial.println("Pedestrian request: POST /api/v1/pedestrians/request");
  }
  previouslyPressed = pressed;
}
