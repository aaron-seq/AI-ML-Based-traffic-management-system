"""Real-time WebSocket feed.

Clients receive every event the system publishes -- phase changes, detections,
emergency pre-emptions, pedestrian requests and periodic status snapshots --
as JSON envelopes of the form ``{"type": ..., "data": ..., "timestamp": ...}``.

The previous implementation polled the controller on a fixed timer inside the
socket handler and serialised models with ``.dict()``, which produced raw
``datetime`` objects that ``send_json`` cannot encode. This version subscribes
to the event bus and serialises in JSON mode.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ...core import metrics
from ...core.config import settings
from ...core.events import event_bus
from ...core.logger import get_application_logger
from ...core.security import extract_api_key
from ...models.traffic_models import WebSocketEnvelope, utc_now
from ...services.container import container

logger = get_application_logger("api.websocket")

router = APIRouter(tags=["realtime"])

#: Sent when no event has occurred, so idle connections are not dropped by
#: intermediate proxies.
_HEARTBEAT_INTERVAL_SECONDS = 20.0


def _authorised(websocket: WebSocket, token: str | None) -> bool:
    """WebSocket clients cannot always set headers, so a query token is allowed."""
    if not settings.api_key:
        return True

    import secrets

    provided = token or extract_api_key(websocket)  # type: ignore[arg-type]
    return bool(provided) and secrets.compare_digest(provided, settings.api_key)


@router.websocket("/ws/traffic-updates")
async def traffic_updates(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="API key, when one is configured"),
) -> None:
    """Stream live traffic events to a dashboard or control room display."""
    if not _authorised(websocket, token):
        await websocket.close(code=4401, reason="Invalid or missing API key")
        return

    await websocket.accept()
    metrics.set_websocket_connections(event_bus.subscriber_count + 1)
    logger.info("WebSocket client connected")

    try:
        async with event_bus.subscribe() as queue:
            await _send_initial_state(websocket)

            while True:
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL_SECONDS)
                except TimeoutError:
                    envelope = WebSocketEnvelope(
                        type="heartbeat", data={"server_time": utc_now().isoformat()}
                    )

                if websocket.client_state is not WebSocketState.CONNECTED:
                    break

                await websocket.send_json(envelope.model_dump(mode="json"))
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as error:  # pragma: no cover - transport level
        logger.warning("WebSocket closed with error: %s", error)
    finally:
        metrics.set_websocket_connections(max(event_bus.subscriber_count - 1, 0))
        if websocket.client_state is WebSocketState.CONNECTED:
            with contextlib.suppress(RuntimeError):
                await websocket.close()


async def _send_initial_state(websocket: WebSocket) -> None:
    """Send a snapshot immediately so the UI renders without waiting for a tick."""
    if container.network is None:
        return

    for controller in container.network.controllers:
        status = await controller.get_current_status()
        envelope = WebSocketEnvelope(type="intersection_status", data=status.model_dump(mode="json"))
        await websocket.send_json(envelope.model_dump(mode="json"))
