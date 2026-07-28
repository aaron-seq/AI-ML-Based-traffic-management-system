"""Aggregates every v1 route module into a single router."""

from __future__ import annotations

from fastapi import APIRouter

from .routes import analytics, detection, emergency, intersections, pedestrians, system, websocket

#: Versioned API surface, mounted at ``/api/v1``.
api_router = APIRouter()
api_router.include_router(detection.router)
api_router.include_router(intersections.router)
api_router.include_router(emergency.router)
api_router.include_router(pedestrians.router)
api_router.include_router(analytics.router)
api_router.include_router(system.router)

#: WebSocket routes are mounted at the root: version negotiation over a socket
#: adds nothing, and existing clients already connect to /ws/traffic-updates.
websocket_router = websocket.router

__all__ = ["api_router", "websocket_router"]
