"""HTTP middleware: security headers, scanner filtering, metrics, request logs."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from .core import metrics
from .core.config import settings
from .core.logger import get_application_logger
from .core.security import get_client_ip, is_suspicious_request, log_security_event

logger = get_application_logger("middleware")

RequestHandler = Callable[[Request], Awaitable[Response]]

#: Paths that should not be rate limited, logged verbosely or counted as traffic.
_INFRASTRUCTURE_PATHS = frozenset({"/health", "/healthz", "/ready", "/metrics"})

#: Collapse high-cardinality path segments so metrics labels stay bounded.
_PATH_NORMALISERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"/intersections/[^/]+"), "/intersections/{intersection_id}"),
    (re.compile(r"/forecast/[^/]+"), "/forecast/{intersection_id}"),
    (re.compile(r"/impact/[^/]+"), "/impact/{intersection_id}"),
    (re.compile(r"/override/[^/]+"), "/override/{alert_id}"),
    (re.compile(r"/[0-9a-fA-F-]{16,}"), "/{id}"),
)


def normalise_path(path: str) -> str:
    """Reduce a request path to a bounded metrics label."""
    trimmed = path.rstrip("/") or "/"
    for pattern, replacement in _PATH_NORMALISERS:
        trimmed = pattern.sub(replacement, trimmed)
    return trimmed


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds standard hardening headers and blocks obvious scanner traffic."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
            # The API returns JSON and never renders HTML, so the strictest
            # policy is also the correct one.
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        }
        if settings.is_production:
            self._headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        if is_suspicious_request(
            request.url.path,
            str(request.query_params),
            request.headers.get("user-agent", ""),
        ):
            client_ip = get_client_ip(request)
            log_security_event(
                "suspicious_request_blocked",
                client_ip,
                {"path": request.url.path, "method": request.method},
                severity="WARNING",
            )
            return self._apply(JSONResponse(status_code=403, content={"detail": "Request blocked."}))

        response = await call_next(request)
        return self._apply(response)

    def _apply(self, response: Response) -> Response:
        for name, value in self._headers.items():
            response.headers.setdefault(name, value)
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records request counts, durations and in-flight gauges."""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        if request.url.path in _INFRASTRUCTURE_PATHS:
            return await call_next(request)

        method = request.method
        endpoint = normalise_path(request.url.path)
        started = time.perf_counter()

        metrics.http_requests_in_progress.labels(method=method, endpoint=endpoint).inc()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as error:
            metrics.record_error(type(error).__name__, "http")
            raise
        finally:
            duration = time.perf_counter() - started
            metrics.http_requests_total.labels(
                method=method, endpoint=endpoint, status_code=status_code
            ).inc()
            metrics.http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)
            metrics.http_requests_in_progress.labels(method=method, endpoint=endpoint).dec()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Tags every request with an id and logs its outcome.

    The id is echoed in the ``X-Request-ID`` response header and included in
    error bodies, so a user-reported failure can be traced straight to its log
    line.
    """

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        if request.url.path in _INFRASTRUCTURE_PATHS:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Request failed: %s %s",
                request.method,
                request.url.path,
                extra={"request_id": request_id, "client_ip": get_client_ip(request)},
            )
            raise

        duration = time.perf_counter() - started
        response.headers["X-Request-ID"] = request_id

        log = logger.warning if response.status_code >= 400 else logger.info
        log(
            "%s %s -> %d in %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            duration,
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "duration_seconds": round(duration, 4),
                "client_ip": get_client_ip(request),
            },
        )
        return response
