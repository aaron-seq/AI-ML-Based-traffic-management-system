# Configuration reference

Every setting is read from a `TRAFFIC_`-prefixed environment variable or a
`.env` file. `ENVIRONMENT` (no prefix) selects the profile.

`cp .env.example backend/.env` gives you an annotated starting point.
`GET /api/v1/system/configuration` audits the running configuration.

## Profiles

| `ENVIRONMENT` | Effect |
|---|---|
| `development` *(default)* | Debug on, API docs served, DEBUG logging, permissive hosts |
| `testing` | In-memory database, persistence off, no file logging, short token lifetimes |
| `production` | Debug off, docs disabled, JSON logs, tighter rate limits, startup audit enforced |

Explicit variables always win over the profile default.

---

## Detection

| Variable | Default | Notes |
|---|---|---|
| `TRAFFIC_MODEL_NAME` | `yolov8n.pt` | See the table below |
| `TRAFFIC_MODEL_CACHE_DIRECTORY` | `./models` | Put this on persistent storage |
| `TRAFFIC_DETECTION_CONFIDENCE_THRESHOLD` | `0.35` | Lower catches distant vehicles, admits false positives |
| `TRAFFIC_NON_MAX_SUPPRESSION_THRESHOLD` | `0.45` | Raise where vehicles overlap heavily |
| `TRAFFIC_DETECTION_IMAGE_SIZE` | `640` | Cost is roughly quadratic |
| `TRAFFIC_ENABLE_GPU_ACCELERATION` | `false` | Needs a CUDA build of torch |
| `TRAFFIC_MAX_CONCURRENT_INFERENCES` | `2` | Raise only with cores or VRAM to spare |
| `TRAFFIC_TRACKER_CONFIG` | `bytetrack.yaml` | `botsort.yaml` is more accurate, slower |
| `TRAFFIC_VIDEO_FRAME_STRIDE` | `3` | Analyse every Nth frame |
| `TRAFFIC_VIDEO_MAX_FRAMES` | `300` | Bounds request time |

### Choosing a model

| Model | Size | CPU latency* | When |
|---|---|---|---|
| `yolov8n.pt` | 6 MB | ~150–200 ms | Default. Ample for queue counting |
| `yolov8s.pt` | 22 MB | ~400 ms | Small or distant vehicles |
| `yolov8m.pt` | 50 MB | ~1 s | Accuracy matters more than latency |
| `yolo11n.pt` | 6 MB | ~150 ms | Newer architecture, same interface |

\* One modern laptop core at 640 px. A GPU is roughly 10–20× faster. First
inference includes warm-up and can take several seconds — that is not the
steady-state figure.

**Tuning confidence.** Missing stopped vehicles under-serves an approach;
phantom vehicles hold green on an empty one. Start at 0.35, then check
`average_confidence` under *Insights → Pipeline* against the annotated images
your camera actually produces.

---

## Signal timing

| Variable | Default | Notes |
|---|---|---|
| `TRAFFIC_MINIMUM_GREEN_DURATION` | `10` | Floor per phase. Below ~7 s vehicles cannot clear |
| `TRAFFIC_MAXIMUM_GREEN_DURATION` | `120` | Ceiling. This is what stops an approach starving |
| `TRAFFIC_DEFAULT_GREEN_SIGNAL_DURATION` | `30` | Used in fixed-time mode |
| `TRAFFIC_YELLOW_SIGNAL_DURATION` | `3` | Local regulation usually mandates this |
| `TRAFFIC_ALL_RED_CLEARANCE_DURATION` | `2` | **Do not set to 0 on real hardware** |
| `TRAFFIC_SECONDS_PER_QUEUED_VEHICLE` | `2.0` | How aggressively green follows demand |
| `TRAFFIC_CONTROL_LOOP_INTERVAL_SECONDS` | `1.0` | Tick rate |

Green time is:

```
clamp(minimum_green + queue_in_pcu × seconds_per_queued_vehicle,
      minimum_green, maximum_green)
```

**Tuning `seconds_per_queued_vehicle`.** Higher means longer greens for busy
approaches and more variable cycles. Around 2.0 s per passenger-car unit
roughly matches the discharge rate, so the green lasts about as long as the
queue takes to clear. Below ~1.0 s queues do not clear in one cycle; above ~4.0
s the cycle becomes long and unpredictable, which pedestrians and side roads
feel most.

**Tuning `maximum_green_duration`.** Too high and a saturated arterial starves
the side road. Too low and the arterial never clears. Start at 2–3× your
expected typical green.

---

## Pedestrians

| Variable | Default | Notes |
|---|---|---|
| `TRAFFIC_PEDESTRIAN_CROSSING_DURATION` | `12` | Walk time. Roughly crossing width ÷ 1.2 m/s |
| `TRAFFIC_PEDESTRIAN_MAX_WAIT_SECONDS` | `90` | Bound on pedestrian delay |

`accessibility_extension` on a request lengthens the walk by half again.

Long waits are not merely inconvenient — they push people to cross against the
signal. Where footfall is high, lower the maximum wait even at some cost to
vehicle throughput.

---

## Corridor coordination

| Variable | Default | Notes |
|---|---|---|
| `TRAFFIC_GREEN_WAVE_ENABLED` | `true` | |
| `TRAFFIC_GREEN_WAVE_DESIGN_SPEED_KPH` | `50` | Should match the posted limit |

Set the design speed to the **posted limit**, not the free-flow speed. Tuning a
green wave above the limit rewards speeding.

---

## Security

| Variable | Default | Notes |
|---|---|---|
| `TRAFFIC_API_KEY` | *(empty)* | Requires `X-API-Key` on writes. Mandatory in production |
| `TRAFFIC_JWT_SECRET_KEY` | *(empty)* | Only for external identity providers. ≥32 chars |
| `TRAFFIC_ALLOWED_ORIGINS` | `localhost:3000` | Comma-separated. `*` rejected in production |
| `TRAFFIC_TRUSTED_HOSTS` | `*` | Host allowlist. Set it in production |
| `TRAFFIC_RATE_LIMIT_REQUESTS_PER_MINUTE` | `120` | Per IP, per process |
| `TRAFFIC_RATE_LIMIT_UPLOAD_REQUESTS_PER_MINUTE` | `20` | Per IP, per process |
| `TRAFFIC_MAX_UPLOAD_SIZE_MB` | `25` | Rejected mid-stream, not buffered |

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Persistence

| Variable | Default | Notes |
|---|---|---|
| `TRAFFIC_PERSISTENCE_ENABLED` | `true` | |
| `TRAFFIC_DATABASE_URL` | SQLite in `./data` | Any SQLAlchemy async URL |
| `TRAFFIC_RETENTION_DAYS` | `30` | Older records pruned on startup |
| `TRAFFIC_DATABASE_ECHO` | `false` | Logs SQL; very noisy |

SQLite is fine for a single instance. For several, use Postgres:

```bash
pip install asyncpg
TRAFFIC_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/traffic
```

If the database is unreachable — or its driver is not installed — the
application logs a warning and continues in memory-only mode.

---

## Field hardware

| Variable | Default | Notes |
|---|---|---|
| `TRAFFIC_HARDWARE_WEBHOOK_URL` | *(empty)* | Empty disables the bridge |
| `TRAFFIC_HARDWARE_WEBHOOK_TOKEN` | *(empty)* | Sent as a bearer token |
| `TRAFFIC_HARDWARE_WEBHOOK_TIMEOUT_SECONDS` | `3.0` | Keep it short; delivery is best-effort |

See [`hardware.md`](hardware.md).

---

## Impact model

| Variable | Default | Notes |
|---|---|---|
| `TRAFFIC_IDLE_FUEL_LITRES_PER_HOUR` | `0.9` | Depends entirely on fleet mix |
| `TRAFFIC_CO2_KG_PER_LITRE_PETROL` | `2.31` | Diesel ≈ 2.68 |
| `TRAFFIC_AVERAGE_VEHICLE_OCCUPANCY` | `1.4` | Far higher on a bus corridor |
| `TRAFFIC_VALUE_OF_TIME_PER_HOUR` | `8.0` | Use your authority's published figure |
| `TRAFFIC_IMPACT_CURRENCY` | `USD` | Label only; no conversion is applied |
| `TRAFFIC_BASELINE_FIXED_CYCLE_SECONDS` | `120` | The plan adaptive control is compared against |

These defaults are mid-range published values and **will be wrong for your
site**. See [`impact-model.md`](impact-model.md).

---

## Logging

| Variable | Default | Notes |
|---|---|---|
| `TRAFFIC_LOG_LEVEL` | `INFO` | |
| `TRAFFIC_LOG_JSON` | `false` | On automatically in production |
| `TRAFFIC_ENABLE_FILE_LOGGING` | `true` | Rotates at 10 MB, 5 backups |
| `TRAFFIC_LOG_FILE_PATH` | `./logs/traffic_system.log` | A read-only filesystem disables this rather than failing |

---

## Dashboard

Read at **build time** and baked into the bundle, so redeploy after changing
them.

| Variable | Notes |
|---|---|
| `VITE_API_URL` | Empty means same-origin (the dev proxy handles it) |
| `VITE_WS_URL` | Derived from `VITE_API_URL` when unset |
| `VITE_API_KEY` | Must match `TRAFFIC_API_KEY` when one is set |

> A key baked into a browser bundle is visible to anyone who loads the page.
> For anything beyond a trusted network, terminate authentication at a proxy in
> front of the API instead.
