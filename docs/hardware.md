# Connecting real signal hardware

> ## Read this first
>
> Traffic signals on a public road are **safety-critical infrastructure**.
> Getting them wrong injures people. This project is a demonstration and
> research platform; it is not certified for use on a public highway, and this
> document is not a substitute for the standards and approvals that apply where
> you are.
>
> Any real installation needs:
>
> - **An independent hardware conflict monitor** — a separate device that
>   watches the actual lamp outputs and forces the intersection to flashing
>   amber if it ever sees conflicting greens. It must not depend on this
>   software being correct.
> - **A local failsafe.** If commands stop arriving, the controller must fall
>   back to flashing amber or a safe fixed plan on its own. Never leave a
>   signal holding its last state.
> - **Approval from the responsible road authority**, and compliance with local
>   standards (MUTCD in the US, TSRGD in the UK, the relevant national standard
>   elsewhere).
>
> Use this on a bench, a model intersection, a private test track or a
> simulator. Do not wire it to a live junction without the above.

## How the bridge works

Set `TRAFFIC_HARDWARE_WEBHOOK_URL` and every phase change is POSTed to your
device:

```bash
TRAFFIC_HARDWARE_WEBHOOK_URL=http://192.168.1.50/signals
TRAFFIC_HARDWARE_WEBHOOK_TOKEN=a-shared-secret     # sent as a bearer token
TRAFFIC_HARDWARE_WEBHOOK_TIMEOUT_SECONDS=3.0
```

Delivery is asynchronous and best-effort. A slow or offline device never stalls
the control loop; when the queue backs up, the **oldest** command is dropped,
because field hardware only cares about the newest state. Statistics are exposed
at `GET /api/v1/system/hardware`.

## Wire format

```json
{
  "intersection_id": "main_intersection",
  "phase": "north_south_green",
  "emergency": false,
  "pedestrian": false,
  "timestamp": "2026-07-28T02:19:51.828Z",
  "signals": {
    "north": { "state": "G", "remaining_seconds": 28 },
    "south": { "state": "G", "remaining_seconds": 28 },
    "east":  { "state": "R", "remaining_seconds": 28 },
    "west":  { "state": "R", "remaining_seconds": 28 }
  },
  "compact": "E:R28,N:G28,S:G28,W:R28"
}
```

| Code | Aspect |
|---|---|
| `R` | Red |
| `Y` | Yellow |
| `G` | Green |
| `FR` | Flashing red |
| `FY` | Flashing yellow |
| `O` | Off |

The `compact` field is a single line for microcontrollers with no room for a
JSON parser: approaches are sorted alphabetically (east, north, south, west) and
joined with commas.

## Arduino / ESP32 gateway

[`Traffic_signal.ino`](../Traffic_signal.ino) is a working sketch that runs an
HTTP server, accepts the payload above, drives twelve LEDs, and — importantly —
falls back to flashing amber when commands stop.

### Wiring

```
ESP32          Signal head
─────          ───────────
GPIO 16 ──[220Ω]── North red
GPIO 17 ──[220Ω]── North yellow
GPIO 18 ──[220Ω]── North green
GPIO 19 ──[220Ω]── South red
GPIO 21 ──[220Ω]── South yellow
GPIO 22 ──[220Ω]── South green
GPIO 23 ──[220Ω]── East  red
GPIO 25 ──[220Ω]── East  yellow
GPIO 26 ──[220Ω]── East  green
GPIO 27 ──[220Ω]── West  red
GPIO 32 ──[220Ω]── West  yellow
GPIO 33 ──[220Ω]── West  green
GND     ─────────  common cathode
```

For real lamps, drive relays or solid-state relays from these pins — never mains
directly from a GPIO. Keep the mains side physically and electrically isolated.

### Simulating it first

[Wokwi](https://wokwi.com/) runs the sketch in a browser with virtual LEDs, so
the whole loop can be tested before any hardware exists. The `Wokwi` file in the
repository root has the project link.

## Testing without a device

Point the webhook at any HTTP endpoint that logs what it receives:

```bash
# Terminal 1 — a webhook sink
python -m http.server 9000 &

# Terminal 2 — or something that prints the body
npx --yes http-echo-server 9000

# Terminal 3
TRAFFIC_HARDWARE_WEBHOOK_URL=http://localhost:9000 uvicorn app.main:app
```

Then confirm delivery:

```bash
curl -s localhost:8000/api/v1/system/hardware | jq
```

```json
{ "enabled": true, "endpoint": "http://localhost:9000", "pending": 0, "sent": 42, "failed": 0, "dropped": 0 }
```

## Other integration paths

**Existing controllers (NTCIP).** Most commercial cabinet controllers speak
NTCIP 1202 over SNMP. Write a small adapter that receives the webhook and
translates it into the appropriate SNMP set — that keeps this software out of
the safety-critical path and lets the certified controller retain final
authority.

**PLCs.** Modbus TCP and similar are straightforward from a webhook receiver.
Map each approach's aspect to a coil.

**MQTT.** Bridge the webhook onto a broker if the rest of your estate is
MQTT-based. Publish to `traffic/{intersection_id}/signals` and let devices
subscribe.

**Reading sensors back in.** Anything that can make an HTTP request can supply
demand via `POST /api/v1/intersections/{id}/counts` — inductive loops, radar,
magnetometers, a pedestrian push-button wired to
`POST /api/v1/pedestrians/request`.

## Failure behaviour to implement on the device

| Condition | Required behaviour |
|---|---|
| No command for > 10 s | Flashing amber on all approaches |
| Malformed command | Ignore it, keep the last valid state, keep the watchdog running |
| Conflicting greens requested | Refuse, and fall back to flashing amber |
| Power restored | Start in flashing amber until the first valid command |

The bundled sketch implements the first of these. **Implement all of them** on
anything that drives real lamps, and keep an independent conflict monitor in the
circuit regardless.
