# API reference

Base URL: `http://localhost:8000`. Versioned endpoints live under `/api/v1`.
Interactive documentation is served at `/api/docs` (disabled in production).

## Authentication

When `TRAFFIC_API_KEY` is set, every write endpoint requires the key:

```bash
curl -H "X-API-Key: $TRAFFIC_API_KEY" ...
# Authorization: Bearer <key> also works
```

Read endpoints stay open. When the variable is empty the whole API is
unauthenticated — fine for a local demo, refused by the production
configuration audit.

WebSocket clients cannot always set headers, so they may pass the key as a
query parameter: `ws://host/ws/traffic-updates?token=<key>`.

## Errors

Every error is JSON and carries a `request_id` that appears in the server logs:

```json
{
  "detail": "Unknown intersection: elm_st. List the registered intersections with GET /api/v1/intersections.",
  "path": "/api/v1/intersections/elm_st",
  "request_id": "a3f19c2b8e4d7061"
}
```

| Status | Meaning |
|---|---|
| `400` | Malformed request (empty upload, bad stream scheme) |
| `401` | Missing or wrong API key |
| `403` | Feature disabled, or the request looked like a scanner probe |
| `404` | Unknown intersection or alert |
| `409` | Intersection id already registered |
| `413` | Upload exceeds `TRAFFIC_MAX_UPLOAD_SIZE_MB` |
| `415` | Wrong file type, or content that is not really an image |
| `422` | Validation failure (`errors` lists each issue) |
| `429` | Rate limited (`Retry-After` header) |
| `503` | A required service is still starting or unavailable |

---

## Detection

### `POST /api/v1/detection/image`

Detect vehicles and pedestrians in a still image, and by default feed the
resulting queues into the signal controller.

| Query parameter | Default | Meaning |
|---|---|---|
| `intersection_id` | `main_intersection` | Which intersection to update |
| `save_annotated` | `true` | Write an annotated copy to `output_images/` |
| `confidence` | *(config)* | Override the confidence threshold |
| `update_signals` | `true` | Feed counts into the controller |

```bash
curl -X POST "http://localhost:8000/api/v1/detection/image?intersection_id=main_intersection" \
     -F "image=@test_images/1.jpg"
```

```json
{
  "detection_id": "6b0a…",
  "total_vehicles": 17,
  "pedestrian_count": 0,
  "lane_counts": { "north": 7, "south": 3, "east": 4, "west": 3 },
  "total_passenger_car_units": 20.0,
  "busiest_lane": "north",
  "processing_time": 0.178,
  "annotated_image_path": "output_images/1_…_annotated.jpg",
  "detected_vehicles": [
    {
      "vehicle_type": "car",
      "confidence": 0.87,
      "bounding_box": { "x1": 7, "y1": 261, "x2": 99, "y2": 334, "area": 6716 },
      "center": { "x": 0.159, "y": 0.795 },
      "lane": "west",
      "passenger_car_units": 1.0
    }
  ]
}
```

Annotated images are served from `/static/<filename>`.

### `POST /api/v1/detection/video`

Track road users through a clip. Tracking is what makes `unique_vehicles`
meaningful — the same car across thirty frames counts once.

| Query parameter | Default | Meaning |
|---|---|---|
| `frame_stride` | `3` | Analyse every Nth frame |
| `max_frames` | `300` | Cap on frames analysed |
| `metres_per_pixel` | — | Ground sampling distance; **required for speeds** |
| `include_frames` | `false` | Include per-frame detail (large response) |

```json
{
  "frames_analysed": 100,
  "duration_seconds": 30.0,
  "unique_vehicles": 42,
  "vehicle_type_breakdown": { "car": 35, "bus": 3, "truck": 4 },
  "flow_rate_vehicles_per_hour": 5040.0,
  "average_speed_kph": 38.5,
  "sampling_note": null
}
```

Two fields are deliberately nullable rather than guessed:

- **`average_speed_kph`** is `null` without `metres_per_pixel`. Pixel
  displacement alone cannot yield a speed, and inventing a scale would produce
  authoritative-looking nonsense.
- **`flow_rate_vehicles_per_hour`** is `null` when the clip is shorter than 10
  seconds, with `sampling_note` explaining why. Scaling a 2-second sample to an
  hour multiplies it by 1800 — one such clip reported 36,000 vehicles/hour,
  which is roughly ten vehicles per second through a single junction.

### `POST /api/v1/detection/stream`

Sample a bounded number of frames from a live RTSP or HTTP camera and return.
Poll it on a schedule to keep an intersection continuously fed.

```bash
curl -X POST "http://localhost:8000/api/v1/detection/stream" \
     --data-urlencode "stream_url=rtsp://camera.local/stream1" \
     -G --data "max_frames=60"
```

### `GET /api/v1/detection/performance`

Model name, device, threshold and running latency statistics.

---

## Intersections

### `GET /api/v1/intersections`

One row per registered intersection.

### `GET /api/v1/intersections/{id}`

Full live state: current phase, per-approach aspects and countdowns, queues,
capacity units, congestion banding, pedestrian and emergency flags.

```json
{
  "intersection_id": "main_intersection",
  "current_phase": "north_south_green",
  "green_direction": ["north", "south"],
  "traffic_signals": {
    "north": { "current_state": "green", "remaining_time": 28 },
    "east":  { "current_state": "red",   "remaining_time": 28 }
  },
  "vehicle_counts": { "north": 8, "south": 1, "east": 1, "west": 1 },
  "average_wait_time": 10.84,
  "congestion_level": "moderate",
  "adaptive_mode": true
}
```

### `POST /api/v1/intersections`

Register an intersection. `distance_from_previous_metres` positions it on the
corridor and feeds the green-wave calculation.

```json
{ "intersection_id": "elm_st", "name": "Elm Street", "distance_from_previous_metres": 420 }
```

### `POST /api/v1/intersections/{id}/counts`

Drive the controller from any source — inductive loops, radar, a
microsimulation, a load test. No camera or model required.

```bash
curl -X POST http://localhost:8000/api/v1/intersections/main_intersection/counts \
     -H 'Content-Type: application/json' \
     -d '{"counts": {"north": 18, "south": 3, "east": 2, "west": 1}}'
```

### `PATCH /api/v1/intersections/{id}/plan`

Retune timing at runtime. Only the fields you send are changed.

```json
{ "minimum_green_duration": 12, "seconds_per_queued_vehicle": 2.5, "adaptive_mode": true }
```

Setting `adaptive_mode: false` switches to a fixed-time plan — useful as a
baseline when measuring what adaptive control is actually contributing.

### `GET /api/v1/intersections/coordination`

Green-wave offsets for the corridor.

```json
{
  "design_speed_kph": 50.0,
  "common_cycle_seconds": 74,
  "corridor": ["main_intersection", "elm_st"],
  "offsets_seconds": { "main_intersection": 0.0, "elm_st": 30.2 },
  "corridor_length_metres": 420.0
}
```

`elm_st` starts its green 30.2 s after `main_intersection`, which is how long a
platoon takes to travel 420 m at 50 km/h.

### `POST /api/v1/intersections/{id}/start` · `/stop`

Start or stop the control loop. Stopping freezes the signals in their current
aspect — field hardware should fall back to flashing amber when commands stop
arriving.

---

## Emergency pre-emption

### `POST /api/v1/emergency/override`

```json
{
  "emergency_type": "ambulance",
  "detected_lane": "north",
  "priority_level": 5,
  "override_duration": 45,
  "intersection_id": "main_intersection"
}
```

Returns `202` with the created alert. The pre-empted approach gets green and
every other approach red — still via the phase machine, so conflicting
movements receive yellow and clearance first.

`alert_id` is generated when omitted. When several alerts are active, the
highest `priority_level` controls the intersection.

### `GET /api/v1/emergency/active` · `DELETE /api/v1/emergency/override/{alert_id}`

List active pre-emptions, or release one before its window expires. Alerts also
expire automatically after `override_duration`.

---

## Pedestrians

### `POST /api/v1/pedestrians/request`

```json
{ "crossing": "north", "pedestrian_count": 3, "accessibility_extension": true }
```

Served at the next all-red boundary. `accessibility_extension` lengthens the
walk phase by half again for wheelchair users, older people and children.

A request waiting longer than `TRAFFIC_PEDESTRIAN_MAX_WAIT_SECONDS` pre-empts
the running vehicle phase, so pedestrian delay is bounded regardless of how
heavy vehicle demand is.

### `GET /api/v1/pedestrians/pending` · `GET /api/v1/pedestrians/policy`

---

## Analytics, forecast and impact

### `GET /api/v1/analytics/summary?period=current|hourly|daily`

Rolling traffic statistics, approach distribution, demand trend and pipeline
health (latency, confidence).

### `GET /api/v1/analytics/history?hours=24&limit=500`

Historical detections. Served from the database when persistence is enabled;
otherwise from this process's memory, with a note saying so.

### `GET /api/v1/analytics/heatmap?hours=24`

Counts bucketed by hour and approach.

### `GET /api/v1/forecast/{id}`

```json
{
  "method": "seasonal-ewma",
  "observations_used": 120,
  "confidence": 0.71,
  "points": [
    {
      "horizon_minutes": 15,
      "expected_vehicles": 19.05,
      "lower_bound": 6.63,
      "upper_bound": 31.48,
      "expected_congestion": "heavy"
    }
  ]
}
```

With too little history it returns no points and a `notes` field saying what it
needs, rather than extrapolating from a handful of samples.

### `GET /api/v1/impact/{id}`

Modelled savings against a fixed-time baseline, with the assumptions attached.

```json
{
  "vehicles_served": 19,
  "delay_saved_seconds": 173.95,
  "delay_reduction_percent": 36.47,
  "fuel_litres_saved": 0.043,
  "co2_kg_avoided": 0.1,
  "economic_value_saved": 0.54,
  "currency": "USD",
  "assumptions": {
    "method": "Webster uniform delay, adaptive plan vs fixed-time baseline",
    "caveat": "Modelled estimate, not a measurement…"
  }
}
```

See [`impact-model.md`](impact-model.md) for the derivation.

### `GET /api/v1/impact/{id}/cumulative`

Running totals plus a naive annual projection, labelled with its confidence.

---

## System

| Endpoint | Purpose |
|---|---|
| `GET /health` | Per-service readiness and host resources |
| `GET /api/v1/system/info` | Version, live capabilities, model, signal plan |
| `GET /api/v1/system/configuration` | Audit for production-unsafe settings |
| `GET /api/v1/system/hardware` | Field bridge delivery statistics |
| `GET /metrics` | Prometheus exposition |

---

## WebSocket

`ws://localhost:8000/ws/traffic-updates`

Every message uses the same envelope:

```json
{ "type": "phase_change", "data": { … }, "timestamp": "2026-07-28T02:19:51.828Z" }
```

| `type` | Emitted when |
|---|---|
| `intersection_status` | Periodic snapshot; also sent immediately on connect |
| `phase_change` | The controller enters a new phase |
| `cycle_completed` | A full cycle finishes |
| `vehicle_detection` | An image detection completes |
| `video_analysis` | A video or stream analysis completes |
| `emergency_alert` / `emergency_cleared` | Pre-emption raised or released |
| `pedestrian_request` / `pedestrian_served` | Crossing requested or served |
| `counts_updated` | Counts submitted directly |
| `heartbeat` | 20 s of silence, so proxies keep the socket open |

```javascript
const socket = new WebSocket('ws://localhost:8000/ws/traffic-updates');
socket.onmessage = ({ data }) => {
  const { type, data: payload } = JSON.parse(data);
  if (type === 'intersection_status') render(payload);
};
```

Slow clients have their oldest messages dropped rather than the server buffering
without limit — for live state, the newest snapshot is the one that matters.

---

## Rate limits

| Endpoint group | Default |
|---|---|
| General | 120 requests/minute per IP |
| Detection uploads | 20 requests/minute per IP |

Limits are per process. Behind several workers, put a shared limiter in the
reverse proxy for a strict global cap.
