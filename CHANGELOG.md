# Changelog

Notable changes to this project. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- **CI referenced a Trivy action tag that no longer exists.** `trivy-action`'s
  tags were force-pushed to credential-stealing commits on 19 March 2026
  ([CVE-2026-33634](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23));
  the tag we used was never restored, so the security job could not start.
  Every action is now pinned to a full commit SHA (Trivy to the advisory's
  known-good `57a97c7`, binary v0.69.3), and Dependabot keeps the pins current.
  This repository ran no workflows during the attack window.
- **The security job could never have passed.** Bandit flagged the API binding
  to all interfaces by default (B104), and `pip-audit -r requirements.txt` would
  have audited a CUDA torch build rather than what we install. `api_host` now
  defaults to `127.0.0.1` (containers pass `--host 0.0.0.0` explicitly), and the
  audit runs against the installed environment — with torch's `+cpu` label
  stripped, since PyPI's feed otherwise skips it. Both audits now block.
- Raised floors past published advisories: `torch>=2.13.0` (PYSEC-2025-194 and
  earlier), `setuptools>=83.0.0` (GHSA-h35f-9h28-mq5c), `pytest>=9.0.3`
  (CVE-2025-71176), plus dev-only npm fixes for vitest, undici, brace-expansion,
  nanoid and source-map-js. The shipped dashboard bundle had none.
- **The dashboard page was served without its security headers.** nginx drops
  inherited `add_header` lines in any location that declares its own, and the
  `index.html` and `/assets/` locations set `Cache-Control` — so `/`, every SPA
  route and every asset went out without `X-Frame-Options`, `nosniff` or
  `Referrer-Policy`, leaving the emergency pre-emption button framable. The
  headers now live in one snippet included wherever headers are set, and the
  Docker smoke test asserts them on the running image. The dashboard also
  stopped proxying `/metrics`; Prometheus scrapes the backend directly.
- **Grafana defaulted to `admin`/`admin`, and Redis was published unauthenticated
  on the host** whenever their Compose profiles were enabled. Monitoring now lives in `docker-compose.monitoring.yml` and
  refuses to start without `GRAFANA_PASSWORD`; Prometheus binds to loopback.

### Fixed

- **Every documented way to set a list setting crashed the backend at start-up.**
  `TRAFFIC_TRUSTED_HOSTS=*`, a single hostname, or comma-separated
  `TRAFFIC_ALLOWED_ORIGINS` all raised `SettingsError`: pydantic-settings
  JSON-decodes list fields from the environment before any validator runs, so
  only a JSON array worked. That covered `.env.example`'s defaults, the
  production recipe and the values Compose hardcoded. The fields are now
  `NoDecode`; comma-separated values and JSON arrays both work, and a broken
  array is rejected instead of being split into entries that match nothing.
- **The dashboard container could never start.** It runs as the `nginx` user,
  but the stock config writes its pid to `/run` and its temp files to
  `/var/cache/nginx`, both root-owned; nginx exited with `mkdir()
  "/var/cache/nginx/client_temp" failed (13: Permission denied)`. CI had only
  ever built the image. Both paths now belong to the unprivileged user, and CI
  runs the image.
- **A production host allowlist turned Compose's own probes into 400s.** The
  health check (`Host: localhost`) and the Prometheus scrape
  (`Host: backend`) are now always allowed; unknown hosts are still rejected.
- **Video tracking pip-installed a package at runtime, or failed offline.**
  ByteTrack needs `lap`, which Ultralytics does not declare; it installs it on
  first use instead. CI passed only because runners are online. `lap` is now a
  declared dependency and `YOLO_AUTOINSTALL=false` stops the server modifying
  its own environment.
- **Two OpenCV builds were installed into one `cv2/` directory.** Ultralytics
  pulls in `opencv-python` while we pinned `opencv-python-headless`; the version
  that actually loaded (5.0) was not the one pinned (4.12), and uninstalling
  either deleted the shared module. Only `opencv-python` is declared now.
- **Docker Compose ignored the documented production settings.**
  `TRAFFIC_ALLOWED_ORIGINS` and `TRAFFIC_TRUSTED_HOSTS` were hardcoded, so the
  values `docs/deployment.md` puts in `.env` never reached the container and
  production ran with wildcard trusted hosts. They are now passed through.
- The README promised "Grafana alerts"; the rules are Prometheus rules and
  nothing routes them. The wording and deployment checklist now say so.

### Removed

- Dependencies nothing imported: `redis`, `aiofiles`, `structlog`, `orjson`,
  `gunicorn`, `cryptography`, `PyJWT`.
- The Redis settings and Compose service: nothing read them, though the
  comments claimed shared rate limiting.
- The JWT helpers and `TRAFFIC_JWT_SECRET_KEY`. No endpoint ever accepted a
  token, yet production demanded the secret. Settings use `extra="ignore"`, so
  an existing `.env` that still sets these keeps working.
- The Codecov upload, which had failed on every run ("Token required") behind
  `continue-on-error`. CI now enforces a coverage floor and writes the report to
  the job summary instead.

## [3.0.0] — 2026-07-28

A substantial rewrite. The previous release documented capabilities it did not
have: vehicle detection failed to initialise at all, the emergency endpoint
returned 500 on every call, and the frontend had no entry point and could not
be built. This release makes the documented system real, and adds the
capabilities that turn it from a demo into something deployable.

### Fixed

Three of these were found only by running the finished system rather than by
reading it or trusting the test suite.

- **One video upload silently degraded every later image detection.**
  `YOLO.track(persist=True)` attaches stateful trackers to the model's predictor
  and leaves them attached, so sharing one handle between tracking and
  still-image detection filtered every subsequent `predict()` through stale
  track state. Measured on real photos, detection fell from 11 vehicles to 3 and
  from 15 to 1 — no error, no log line, just quietly wrong queue counts driving
  signal timing. Tracking now uses a dedicated model handle, and the tracker is
  reset at the start of each video so ids cannot leak between uploads.
- **Field hardware stopped receiving commands whenever no dashboard was open.**
  The broadcast loop skipped its whole tick when the WebSocket subscriber count
  was zero, so closing the last browser tab stopped driving the physical
  signals. Hardware delivery no longer depends on an observer.
- **Flow rate was extrapolated from arbitrarily short samples.** A 2.6-second
  clip reported 36,000 vehicles/hour — about ten per second through one
  junction. Below a ten-second sample the figure is now withheld, with a
  `sampling_note` explaining why.
- **Prometheus could not start under Docker Compose.** `prometheus.yml` listed
  `alerts.yml` in `rule_files`, but the compose service never mounted it.
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

- 291 backend tests (88% coverage), 16 frontend unit tests and 14 Playwright
  end-to-end tests, from a baseline of 5 failures, 15 errors and 2 collection
  errors.
- The full backend suite runs in about twelve seconds with no model weights or
  GPU.
- `mypy app` is clean; `ruff check` and `ruff format --check` are clean.
- Load-tested at 50 concurrent users: 864 requests, 0.00% errors, p95 36 ms.
  The locust profile scores a 429 as backpressure rather than a failure, since
  rate limiting is keyed on client IP and a load generator is a single IP.
- Added `.dockerignore` for both build contexts, cutting them from 77 MB and
  323 MB to 0.3 MB each.

Not verified here: the Docker images themselves were never built, because this
environment has no Docker daemon. The Dockerfiles, compose file and their
referenced paths were validated statically only.

---

## [2.0.0] — 2025

FastAPI backend, YOLOv8 detection service and initial React scaffolding. See
the git history for detail.

## [1.0.0]

Original Pygame simulation with darkflow-based detection.
