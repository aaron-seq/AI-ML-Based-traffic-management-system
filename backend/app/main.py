"""ASGI entry point for the AI Traffic Management System.

Composition only: lifecycle, middleware and routing. All behaviour lives in
``app.services`` and ``app.api``.

Run it with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api.router import api_router, websocket_router
from .api.routes.system import build_health_status
from .core import metrics
from .core.config import settings, validate_configuration
from .core.logger import get_application_logger, setup_logging
from .services.container import container

setup_logging()
logger = get_application_logger("main")

API_V1_PREFIX = "/api/v1"

DESCRIPTION = """
Adaptive traffic signal control driven by computer vision.

**What it does**

* Detects vehicles and pedestrians in images, recorded video and live camera
  streams, using YOLO with multi-object tracking.
* Adapts signal timing to measured demand through a phase-based state machine
  that cannot produce conflicting greens.
* Coordinates a corridor of intersections with green-wave offsets.
* Pre-empts signals for emergency vehicles and gives pedestrians bounded waits.
* Forecasts demand 5-60 minutes ahead and models the delay, fuel and CO2 saved
  against a fixed-time baseline.

**Getting started** - upload an intersection photo to `POST /api/v1/detection/image`,
then read `GET /api/v1/intersections/main_intersection` to see the signals respond.
No camera? Post counts straight to `POST /api/v1/intersections/{id}/counts`.

Live updates stream over `ws://<host>/ws/traffic-updates`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start and stop every service alongside the ASGI application."""
    logger.info(
        "Starting %s v%s (%s)",
        settings.application_name,
        settings.application_version,
        settings.environment,
    )

    problems = validate_configuration()
    for problem in problems:
        # Loud, but not fatal: refusing to boot would take a running
        # intersection offline over a misconfigured optional setting.
        logger.error("Configuration problem: %s", problem)
    if problems and settings.is_production:
        logger.error(
            "%d configuration problem(s) detected in production. Review GET /api/v1/system/configuration.",
            len(problems),
        )

    await container.startup()
    _mount_static_files(app)

    try:
        yield
    finally:
        logger.info("Shutting down %s", settings.application_name)
        await container.shutdown()


def _mount_static_files(app: FastAPI) -> None:
    """Serve annotated detection output, once the directory exists."""
    output_directory = Path("./output_images")
    if not output_directory.exists():
        return
    # Not every entry in app.routes exposes .path (FastAPI wraps included
    # routers), so probe defensively rather than assuming the attribute.
    if any(getattr(route, "path", None) == "/static" for route in app.routes):
        return
    app.mount("/static", StaticFiles(directory=str(output_directory)), name="static")


def create_application() -> FastAPI:
    """Build the configured FastAPI application."""
    app = FastAPI(
        title=settings.application_name,
        description=DESCRIPTION,
        version=settings.application_version,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.docs_enabled else None,
        redoc_url="/api/redoc" if settings.docs_enabled else None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
        contact={"name": "Aaron Sequeira", "url": "https://github.com/aaron-seq"},
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    )

    _register_middleware(app)
    _register_exception_handlers(app)

    app.include_router(api_router, prefix=API_V1_PREFIX)
    app.include_router(websocket_router)

    _register_root_routes(app)
    return app


def _register_middleware(app: FastAPI) -> None:
    """Install middleware.

    Starlette runs middleware in reverse registration order, so the last one
    added is outermost. Request context is registered last and therefore wraps
    everything, giving every log line and error body a request id.
    """
    from .middleware import MetricsMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=1024)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=settings.allowed_methods,
        allow_headers=settings.allowed_headers,
        expose_headers=["X-Request-ID"],
    )

    # The previous version pinned production to localhost only, which rejected
    # every request once deployed. Hosts are now configurable and default to
    # permissive, with validate_configuration() flagging a wildcard in prod.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestContextMiddleware)


def _register_exception_handlers(app: FastAPI) -> None:
    """Return consistent JSON errors that always carry a request id."""

    def request_id(request: Request) -> str:
        return getattr(request.state, "request_id", uuid.uuid4().hex[:16])

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "path": request.url.path,
                "request_id": request_id(request),
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Request validation failed.",
                "errors": exc.errors(),
                "path": request.url.path,
                "request_id": request_id(request),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        identifier = request_id(request)
        logger.error(
            "Unhandled %s on %s: %s",
            type(exc).__name__,
            request.url.path,
            exc,
            exc_info=True,
            extra={"request_id": identifier},
        )
        metrics.record_error(type(exc).__name__, "application")
        # Never leak internals to the caller; the request id ties this response
        # to the full traceback in the logs.
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error.",
                "request_id": identifier,
                "hint": "Quote this request_id when reporting the problem.",
            },
        )


def _register_root_routes(app: FastAPI) -> None:
    """Root-level endpoints that sit outside the versioned API."""

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, object]:
        return {
            "name": settings.application_name,
            "version": settings.application_version,
            "environment": settings.environment,
            "documentation": "/api/docs" if settings.docs_enabled else "disabled in this environment",
            "api": API_V1_PREFIX,
            "websocket": "/ws/traffic-updates",
            "health": "/health",
            "metrics": "/metrics",
        }

    @app.get("/health", tags=["system"], summary="Health check")
    async def health():
        """Liveness and readiness for load balancers and orchestrators."""
        return build_health_status()

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        return metrics.get_metrics_response()

    @app.get("/docs", include_in_schema=False)
    async def docs_redirect() -> RedirectResponse:
        """``/docs`` is where people look first; send them to the real path."""
        return RedirectResponse(url="/api/docs" if settings.docs_enabled else "/")


app = create_application()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug_mode,
        log_level=settings.log_level.lower(),
    )
