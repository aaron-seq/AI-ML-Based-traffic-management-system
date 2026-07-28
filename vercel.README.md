# Vercel deployment

`vercel.json` deploys **the dashboard only**.

The backend cannot run on Vercel's serverless runtime: PyTorch plus the YOLO
weights are far larger than the function size limit, inference exceeds the
execution timeout on CPU, and — more fundamentally — the signal controller is a
long-lived stateful process with a background control loop. Serverless functions
are stateless and short-lived, so a signal cycle cannot survive between
invocations.

Deploy the backend somewhere that runs a persistent container (Render, Railway,
Fly.io, a VM, or Kubernetes — see `docs/deployment.md`), then point the
dashboard at it:

```bash
vercel env add VITE_API_URL production   # https://traffic-api.example.com
vercel env add VITE_WS_URL  production   # wss://traffic-api.example.com/ws/traffic-updates
```

Both are read at build time, so redeploy the dashboard after changing them.
Remember to add the dashboard's origin to `TRAFFIC_ALLOWED_ORIGINS` on the
backend.
