# Changelog

Notable changes to this project. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

## [3.0.0] — 2026-07-28

A substantial rewrite. The previous release documented capabilities it did not
have: vehicle detection failed to initialise at all, the emergency endpoint
returned 500 on every call, and the frontend had no entry point and could not
be built. This release makes the documented system real, and adds the
capabilities that turn it from a demo into something deployable.

### Fixed

- **Vehicle detection was completely non-functional.** `ultralytics==8.0.206`
  could not load its own weights under PyTorch ≥ 2.6, whose `torch.load`
  defaults to `weights_only=True`. Every start logged
  `_pickle.UnpicklingError` and the detector reported permanently unavailable,
  so `POST /api/detect-vehicles` returned 503 unconditionally.
- **Emergency override returned 500 on every request.** The API passed a raw
  `dict` to a controller method that expected a Pydantic model, failing with
  `'dict' object has no attribute 'alert_id'`. The endpoint now validates into
  an `EmergencyAlert` before the controller sees it.
- **Most detections were silently discarded.** Lane assignment used four narrow
  rectangular bands covering roughly a fifth of the frame; anything outside
  them was labelled `unknown` and dropped, so the queue counts driving signal
  timing were an arbitrary subset of the real traffic. Replaced with sector
  assignment covering the whole frame.
- **`EmergencyAlert.get_time_since_alert()` did not exist**, so every expiry
  check raised `AttributeError` inside the control loop.
- **WebSocket frames could not be serialised.** Payloads were built with
  Pydantic v1's `.dict()`, leaving raw `datetime` objects that `send_json`
  cannot encode.
- **`SystemHealthStatus` was imported but never defined**, so the model import
  block failed silently at startup and fell back to placeholder classes.
- **Production was unreachable by design**: `TrustedHostMiddleware` was pinned
  to `localhost` and `127.0.0.1` whenever debug mode was off, rejecting every
  request to a deployed instance.
- Naive `datetime.utcnow()` throughout, deprecated from Python 3.12 and unsafe
  to compare against timezone-aware values.
- `processing_time` was validated as `> 0`, so a sufficiently fast detection
  failed schema validation.
- `aioredis`, unmaintained and broken on Python 3.11+, was a hard dependency.

### Added

**Detection**
- Video and live RTSP/HTTP stream analysis with ByteTrack multi-object
  tracking, giving unique vehicle counts, flow rates and — with a supplied
  ground-sampling distance — speed estimates.
- Pedestrian detection, counted separately from vehicles.
- Capacity-weighted queues in passenger-car units, so a bus is not counted as
  one car.

**Control**
- Phase-based signal state machine. Right of way belongs to a phase, so
  conflicting greens are structurally unrepresentable rather than merely
  unlikely. Asserted across 200 consecutive transitions and under concurrent
  pre-emption.
- All-red clearance between conflicting phases.
- Pedestrian phases with a bounded maximum wait that pre-empts vehicle phases,
  plus an accessibility extension for slower crossings.
- Queue discharge modelling, so counts decrement as they are served.
- Green extension when demand arrives mid-phase.
- Runtime signal-plan tuning via `PATCH /api/v1/intersections/{id}/plan`,
  including a fixed-time mode for baseline comparison.

**Network**
- Multi-intersection registry with green-wave offset calculation and a shared
  corridor cycle length.

**Analysis**
- Short-term demand forecasting (seasonal EWMA) that reports its own confidence
  and declines to extrapolate from thin history.
- Impact modelling: delay, fuel, CO₂, person-hours and economic value saved
  against a fixed-time baseline, with the assumptions returned on every
  response. Documented in `docs/impact-model.md`.

**Infrastructure**
- Optional async persistence (SQLite by default, any SQLAlchemy URL) that
  degrades to memory-only rather than blocking startup.
- Hardware bridge: phase changes POSTed to a controller, PLC or the bundled
  Arduino gateway, with best-effort delivery that never stalls the control loop.
- Manual count entry, so the system works without a camera — from loops, radar,
  a simulator or a load test.
- API-key authentication on write endpoints, and a production configuration
  audit exposed at `GET /api/v1/system/configuration`.
- Sliding-window rate limiting with a bounded client map.
- Upload hardening: magic-number checking, Unicode-normalising filename
  sanitisation, streaming size limits.
- Request IDs on every response and error body.
- Prometheus metrics covering signals, detection, pedestrians and impact, plus
  alert rules for a stalled controller, failing detection, persistent queues and
  excessive pedestrian waits.

### Changed

- **Frontend rebuilt from nothing.** The previous version had a single component
  importing five modules that did not exist, no entry point, no build config and
  no lockfile — it could not be installed or built. Replaced with a complete
  React 19 / Vite 8 / Tailwind 4 dashboard: live control, detection, insights,
  corridor and system views.
- Backend restructured into `api/`, `core/`, `models/` and `services/`, with
  `main.py` reduced to composition. Services are owned by a container that
  starts each independently and degrades rather than aborting.
- Dependencies brought current: FastAPI 0.140, Pydantic 2.13, Ultralytics 8.4,
  PyTorch ≥ 2.6, React 19, Vite 8, Tailwind 4.
- API versioned under `/api/v1`.
- Replaced `python-jose` and `passlib` with `PyJWT`; there are no user accounts,
  so password hashing was never used.
- Docker images rebuilt: CPU-only torch by default (~200 MB against ~3 GB), a
  proper virtualenv copy, and an unprivileged runtime user. Added a frontend
  image and nginx configuration.
- CI reworked: Python 3.11–3.13 matrix, Ruff, real end-to-end tests, Trivy and
  Bandit scanning, and Docker image smoke tests.

### Removed

- **Vendored `darkflow`** — a dead TensorFlow 1.x project, unused since the move
  to YOLOv8, and the source of the dependency conflicts referenced throughout
  the earlier history.
- **Vercel full-stack deployment config**, which could not have worked: PyTorch
  exceeds the function size limit and the controller is a stateful long-lived
  process. Vercel now deploys the dashboard only, with the reasoning recorded in
  `vercel.README.md`.
- **E2E tests for an admin login flow that was never built** — they targeted
  `/admin/login`, `session_token` cookies and a dashboard that did not exist.
  Replaced with Playwright specs covering the real UI.
- Stray artifacts: a PowerShell error dump committed as `detection_error.json`,
  a duplicate root `requirements.txt` with stale pins, superseded fix-log
  documents, and unreferenced third-party stock images with unclear licensing.

### Documentation

- README rewritten, including an explicit limitations section.
- New `docs/`: architecture, API reference, deployment, hardware integration,
  the impact model derivation, and a full configuration reference.
- Added `CONTRIBUTING.md`, `SECURITY.md` (with a stated threat model) and this
  changelog.
- Annotated `.env.example` explaining what each setting does and when to change
  it.

### Testing

- 286 backend tests (88% coverage) and 16 frontend unit tests, from a baseline
  of 5 failures, 15 errors and 2 collection errors.
- The full backend suite runs in about ten seconds with no model weights or GPU.

---

## [2.0.0] — 2025

FastAPI backend, YOLOv8 detection service and initial React scaffolding. See
the git history for detail.

## [1.0.0]

Original Pygame simulation with darkflow-based detection.
