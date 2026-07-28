# Deployment

## Where this can and cannot run

The backend is a **long-lived stateful process**: it holds signal state and runs
a background control loop that advances phases every second.

| Platform | Backend | Why |
|---|---|---|
| Docker / Compose | ✅ | Reference deployment |
| Render, Railway, Fly.io | ✅ | Persistent containers |
| A VM, or Kubernetes | ✅ | Full control |
| Vercel, Netlify, Lambda | ❌ | Stateless, short-lived functions |

Serverless is not merely a poor fit — it cannot work. PyTorch plus the weights
exceed function size limits, CPU inference exceeds typical timeouts, and a
signal cycle cannot survive between stateless invocations.

The **dashboard** is a static bundle and deploys anywhere. A common split is the
dashboard on Vercel and the backend on Render.

## Docker Compose

```bash
git clone https://github.com/aaron-seq/AI-ML-Based-traffic-management-system.git
cd AI-ML-Based-traffic-management-system

cat > .env <<'EOF'
ENVIRONMENT=production
TRAFFIC_API_KEY=<python -c "import secrets; print(secrets.token_urlsafe(32))">
TRAFFIC_ALLOWED_ORIGINS=https://traffic.example.gov
TRAFFIC_TRUSTED_HOSTS=traffic.example.gov
EOF

docker compose up -d
docker compose logs -f backend
```

With metrics:

```bash
docker compose --profile monitoring up -d
# Prometheus http://localhost:9090   Grafana http://localhost:3001
```

### Building a smaller image

The default build fetches the CPU-only torch wheel (~200 MB rather than ~3 GB):

```bash
docker build -t traffic-backend ./backend
```

For a GPU host, point the build at a CUDA index:

```bash
docker build --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124 \
             -t traffic-backend-gpu ./backend
```

Then set `TRAFFIC_ENABLE_GPU_ACCELERATION=true` and run with `--gpus all`.

## Render

`render.yaml` is a complete blueprint: a Docker backend with a persistent disk
plus the static dashboard.

1. **New → Blueprint**, point it at your fork.
2. Set the two values marked `sync: false`:
   - `TRAFFIC_ALLOWED_ORIGINS` — the dashboard's origin
   - `TRAFFIC_TRUSTED_HOSTS` — the API hostname
3. On the dashboard service, set `VITE_API_URL` and `VITE_WS_URL` to the backend
   URL and redeploy.

`TRAFFIC_API_KEY` and `TRAFFIC_JWT_SECRET_KEY` are generated automatically and
persist across deploys.

> Avoid the free plan. It sleeps on idle, and a sleeping process is a stopped
> signal controller.

## Railway

```bash
npm install -g @railway/cli
railway login && railway init && railway up
```

`railway.toml` builds from the backend Dockerfile. Set `TRAFFIC_API_KEY`,
`TRAFFIC_ALLOWED_ORIGINS` and `TRAFFIC_TRUSTED_HOSTS` in the dashboard, and
attach a volume at `/app/data` — Railway's filesystem is otherwise ephemeral and
history will not survive a restart.

## The dashboard on Vercel

```bash
vercel env add VITE_API_URL production   # https://traffic-api.example.com
vercel env add VITE_WS_URL  production   # wss://traffic-api.example.com/ws/traffic-updates
vercel --prod
```

Both are read at **build time**, so redeploy after changing them. Add the
Vercel origin to `TRAFFIC_ALLOWED_ORIGINS` on the backend.

## Production checklist

Verify with `GET /api/v1/system/configuration`, which reports anything unsafe.

- [ ] `ENVIRONMENT=production` — disables docs, enables JSON logs, tightens rate limits
- [ ] `TRAFFIC_API_KEY` set to a long random value
- [ ] `TRAFFIC_ALLOWED_ORIGINS` lists real origins, never `*`
- [ ] `TRAFFIC_TRUSTED_HOSTS` lists real hostnames, never `*`
- [ ] TLS terminated at the proxy; `X-Forwarded-For` set by that proxy, not the client
- [ ] `/app/data` and `/app/models` on persistent storage
- [ ] Prometheus scraping `/metrics`, with `monitoring/alerts.yml` loaded
- [ ] A hardware failsafe that drops to flashing amber when commands stop — see [`hardware.md`](hardware.md)
- [ ] Restart policy set (`unless-stopped`, or a Kubernetes liveness probe on `/health`)

### Why `X-Forwarded-For` matters

Rate limiting keys on the client IP, taken from `X-Forwarded-For` when present.
That header is only trustworthy if your proxy **overwrites** it. If the backend
is directly reachable, clients can spoof it and evade the limiter. Either put a
proxy in front, or remove direct network access to the backend port.

## Scaling

The controller holds per-process state, so **do not run multiple uvicorn workers
on one port** — each would keep its own divergent copy of the signal state.

Scale by running one process per intersection group, behind a proxy that routes
by intersection id:

```
                    ┌─ backend-1 → intersections A, B, C
  proxy / ingress ──┼─ backend-2 → intersections D, E, F
                    └─ backend-3 → intersections G, H, I
```

Point every instance at a shared Postgres for analytics:

```bash
pip install asyncpg
TRAFFIC_DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/traffic
```

## Sizing

| Deployment | CPU | RAM | Notes |
|---|---|---|---|
| 1 intersection, manual counts | 1 core | 512 MB | No model loaded |
| 1 intersection, image detection | 2 cores | 2 GB | ~150–200 ms/frame with `yolov8n` |
| 1 intersection, live stream | 4 cores | 4 GB | Or 1 core + a GPU |
| Corridor of 5, streams | GPU | 8 GB | CPU inference will not keep up |

Disk: about 100 MB for the image, plus weights (6–90 MB) and history (roughly
1 MB per 10,000 detections).

## Upgrading

```bash
git pull
docker compose build
docker compose up -d
```

Schema changes are applied automatically by `Base.metadata.create_all` on
startup. There is no destructive migration path — back up `traffic.db` (or your
Postgres database) before a major version bump.

## Troubleshooting

**`vehicle_detector` reports not ready.** Weights failed to download. Check
egress to `github.com`, and disk space in `TRAFFIC_MODEL_CACHE_DIRECTORY`. The
rest of the system keeps working; use manual counts meanwhile.

**Detection is very slow.** First inference includes model warm-up and can take
several seconds. If steady-state latency stays high, reduce
`TRAFFIC_DETECTION_IMAGE_SIZE` to 416, or enable GPU.

**The dashboard shows "Reconnecting".** The WebSocket cannot connect. Check
`VITE_WS_URL`, that the proxy forwards `Upgrade`/`Connection` headers, and — if
an API key is set — that the dashboard was built with a matching `VITE_API_KEY`.

**429 responses under normal load.** Raise
`TRAFFIC_RATE_LIMIT_REQUESTS_PER_MINUTE`, or check that your proxy is setting
`X-Forwarded-For` — without it every request appears to come from the proxy's
single IP and shares one budget.

**Analytics reset after a restart.** Persistence is disabled or the database is
unreachable. `GET /health` reports the `persistence` service; check the startup
logs for the reason.
