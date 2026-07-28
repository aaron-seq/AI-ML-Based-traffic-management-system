# Architecture

How the system is put together, and the reasoning behind the parts that could
reasonably have been built another way.

## Layers

```
backend/app/
├── main.py                    ASGI composition only: lifespan, middleware, routing
├── api/
│   ├── deps.py                dependency providers (services, auth, rate limits)
│   ├── router.py              aggregates v1
│   └── routes/                one module per resource
├── core/
│   ├── config.py              settings, profiles, validation
│   ├── database.py            optional async persistence
│   ├── events.py              in-process pub/sub
│   ├── logger.py              console + JSON logging
│   ├── metrics.py             Prometheus registry
│   └── security.py            rate limiting, API keys, upload hardening
├── models/traffic_models.py   Pydantic schemas — the contract between layers
└── services/
    ├── container.py                    lifecycle and wiring
    ├── intelligent_vehicle_detector.py YOLO + tracking
    ├── adaptive_traffic_manager.py     the signal state machine
    ├── network_coordinator.py          corridor registry + green wave
    ├── forecast_service.py             short-term demand prediction
    ├── impact_service.py               delay/fuel/CO₂ modelling
    ├── analytics_service.py            aggregation and history
    └── hardware_bridge.py              delivery to field devices
```

Dependencies point inward: routes depend on services, services depend on models
and core, and nothing depends on `main.py`. That is what lets the whole service
layer be tested without an HTTP client.

## The signal controller

The controller is the part most worth understanding.

### Phases, not per-signal timers

The obvious design gives every signal head its own countdown and transitions
each one independently. The original version of this project did exactly that.
It mostly works — but nothing in it *structurally* prevents two conflicting
heads from being green at once. Safety depends on the arithmetic lining up, and
any new feature (pre-emption, a pedestrian phase, a manual override) is another
chance for it not to.

Here, right of way belongs to a **phase**:

```
NORTH_SOUTH_GREEN → NORTH_SOUTH_YELLOW → ALL_RED
       ↑                                     ↓
   ALL_RED ← EAST_WEST_YELLOW ← EAST_WEST_GREEN
```

Signal aspects are *derived* from the current phase rather than tracked
independently, so a conflicting green is not merely unlikely — it cannot be
represented. `_aspects_for()` is the single place that decides what each head
shows.

Pedestrian and emergency phases are inserted only at `ALL_RED` boundaries, so a
pre-emption still passes through yellow and clearance rather than cutting
straight from one green to a conflicting one.

`tests/unit/test_traffic_controller.py` asserts this invariant across 200
consecutive transitions and under concurrent pre-emptions.

### Adaptive green

```
green = clamp(minimum_green + queue_in_pcu × seconds_per_vehicle,
              minimum_green,
              maximum_green)
```

Three properties matter:

- **The floor** guarantees a usable green even on an empty approach — vehicles
  arriving during the phase still get through.
- **The ceiling** guarantees no approach starves. Without it, one saturated
  approach would hold green indefinitely.
- **Passenger-car units, not vehicle counts.** Green time discharges road space.
  Ten motorcycles clear far faster than ten buses; weighting each detection by
  its capacity equivalent makes the allocated time match the time needed.

Demand arriving *during* a green extends it up to the ceiling, rather than
waiting a full cycle.

### Queue discharge

After each green, the controller decrements the served queue by
`green_seconds × saturation_flow`. Without this, counts would only ever grow
between camera updates and the timing would drift towards maximum green.

## Detection

### Lane assignment

The frame is split into four sectors radiating from the centre; whichever axis
a detection is further along decides its approach.

The original implementation used four narrow rectangular bands covering about a
fifth of the frame. Anything outside them was labelled `unknown` and silently
dropped — so most detections never reached the controller, and the queue counts
driving signal timing were a small, arbitrary subset of the real traffic. Sector
assignment covers the whole frame: every detection lands on exactly one
approach.

### Tracking

Video and stream analysis run the model with ByteTrack. That turns per-frame
detections into persistent objects, which is what makes unique vehicle counts,
flow rates and speed estimates meaningful. Without it, the same car in thirty
frames is thirty vehicles.

### Concurrency

Inference is synchronous and CPU/GPU-bound, so it runs in a worker thread via
`asyncio.to_thread` and is gated by a semaphore. Without the gate, concurrent
uploads would thrash a single-GPU or small-CPU host and every request would get
slower together.

## Events

Services publish to an in-process `EventBus` without knowing who is listening.
The WebSocket route and the analytics recorder both subscribe.

Each subscriber owns a **bounded** queue. When a dashboard stalls, the bus drops
that subscriber's oldest messages rather than growing memory without limit or
blocking the publisher. For live state, freshness beats completeness — the
newest status is the one that matters.

## Persistence

Optional by design. SQLite via `aiosqlite` needs no setup; any SQLAlchemy URL
works for larger deployments. If the database is unreachable — or its driver
isn't installed — the application logs a warning and continues in memory-only
mode. A signal controller should not refuse to control signals because its
analytics store is down.

`Database.session()` yields `None` when persistence is unavailable, so no call
site needs to branch on configuration.

## Degradation

`ServiceContainer.startup()` starts each service independently and records
failures instead of aborting. The detector — slowest to start and most likely to
fail, since it may need to download weights — starts last. If it fails, the
signal controller, manual count entry, forecasting and the dashboard all keep
working; `/health` reports which capability is missing and why.

## Corridor coordination

`TrafficNetwork` owns one `AdaptiveTrafficManager` per intersection. Green-wave
offsets are `cumulative_distance ÷ design_speed`, so a platoon travelling at the
design speed meets a green at every junction.

Coordinated signals must share a **common cycle length**, or the offsets drift
apart within a few cycles. `coordination_plan()` takes the longest demand-driven
cycle across the corridor, so no intersection is under-served by the shared
plan.

## Request lifecycle

```
Request
  → RequestContextMiddleware   assigns X-Request-ID, logs the outcome
  → MetricsMiddleware          counts, times, tracks in-flight
  → SecurityHeadersMiddleware  hardening headers, scanner filtering
  → TrustedHostMiddleware      Host allowlist
  → CORSMiddleware
  → GZipMiddleware
  → route
      → rate limit → API key → service dependencies → handler
```

Starlette runs middleware in reverse registration order, so request context is
registered last and wraps everything — every log line and error body carries the
same request id.

## Testing strategy

| Suite | Covers |
|---|---|
| `tests/unit/test_traffic_controller.py` | Phase machine, safety invariants, adaptive timing, pre-emption, pedestrians |
| `tests/unit/test_detector.py` | Lane assignment, aggregation, capacity weighting, error handling |
| `tests/unit/test_video_and_hardware.py` | Tracking across frames, speed calibration, field delivery |
| `tests/unit/test_analysis_services.py` | Forecasting, impact model, corridor offsets, analytics |
| `tests/integration/test_api.py` | Every endpoint through the real middleware stack |
| `tests/test_security.py` | Upload hardening, rate limiting, configuration audit |
| `tests/test_models.py` | Schema validation and JSON serialisation |
| `tests/test_resilience.py` | Failure modes: no model, no database, concurrency, floods |

The model is stubbed throughout, so the full suite runs in about ten seconds and
needs no weights or GPU.
