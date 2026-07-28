# Security policy

## Reporting a vulnerability

**Do not open a public issue.** Email
[aaronsequeira12@gmail.com](mailto:aaronsequeira12@gmail.com) with:

- What the issue is and how to reproduce it
- Which version and deployment method
- What an attacker could achieve

Expect an acknowledgement within a few days. Please give a reasonable window to
ship a fix before disclosing publicly.

## Supported versions

| Version | Supported |
|---|---|
| 3.x | ✅ |
| 2.x and earlier | ❌ |

## Threat model

This system can influence traffic signals. Treat it as infrastructure.

### What is defended

| Control | Where |
|---|---|
| API-key authentication on every write endpoint | `core/security.py` |
| Sliding-window rate limiting, per IP | `core/security.py` |
| Filename sanitisation, including Unicode normalisation | `sanitize_filename()` |
| Magic-number checking on uploads, not just extensions | `looks_like_image()` |
| Streaming size limits, aborted mid-upload | `api/routes/detection.py` |
| Host allowlist, CORS allowlist | `main.py` |
| Security headers, including a strict CSP | `middleware.py` |
| Scanner-traffic filtering | `is_suspicious_request()` |
| No secrets or internals in error responses | `main.py` exception handlers |
| Credentials stripped from logged database URLs | `core/database.py` |
| Container runs unprivileged | `backend/Dockerfile` |
| Production configuration audit | `validate_configuration()` |

### What is not defended, by design

- **The API is not authenticated when `TRAFFIC_API_KEY` is empty.** That is a
  convenience for local demos. `GET /api/v1/system/configuration` flags it, and
  the production profile requires a key.
- **Rate limits are per process.** Behind several workers, enforce a global cap
  at the proxy.
- **`X-Forwarded-For` is trusted.** Rate limiting keys on it. If the backend is
  directly reachable, clients can spoof it. Put a proxy in front that
  overwrites the header, or remove direct access to the port.
- **A dashboard `VITE_API_KEY` is public.** Anything baked into a browser bundle
  is visible to whoever loads the page. For untrusted networks, authenticate at
  a proxy instead.
- **There are no user accounts or roles.** A single shared key grants all write
  access. Put an identity-aware proxy in front if you need per-user
  authorisation.

## Deployment hardening

Run the audit first:

```bash
curl -s https://your-host/api/v1/system/configuration | jq
```

Then confirm:

- [ ] `ENVIRONMENT=production`
- [ ] `TRAFFIC_API_KEY` set to a long random value
- [ ] `TRAFFIC_ALLOWED_ORIGINS` and `TRAFFIC_TRUSTED_HOSTS` list real values, never `*`
- [ ] TLS terminated at the proxy
- [ ] The proxy overwrites `X-Forwarded-For`
- [ ] The backend port is not directly reachable from the internet
- [ ] `/metrics` is not publicly exposed — it reveals traffic patterns and internals
- [ ] Dependencies scanned (`pip-audit`, `npm audit`) and images rebuilt regularly

## Physical safety

Security and safety are different problems, and this one matters more.

If this system drives real signal hardware, a compromise or a bug could create
conflicting greens. Software correctness is not an acceptable sole defence:

- Fit an **independent hardware conflict monitor** that watches the actual lamp
  outputs and forces flashing amber on conflict. It must not depend on this
  software.
- Implement a **local failsafe** in the field device: flashing amber when
  commands stop arriving.
- Keep the control network **isolated** from general-purpose networks.
- Obtain approval from the responsible road authority.

See [`docs/hardware.md`](docs/hardware.md).

## Known dependency surface

The largest third-party surface is PyTorch and Ultralytics, pulled in for
inference. Model weights are downloaded from the Ultralytics release channel on
first run. In a locked-down environment, download them once, mount them into
`TRAFFIC_MODEL_CACHE_DIRECTORY`, and block egress — the system starts offline
when the weights are already cached.
