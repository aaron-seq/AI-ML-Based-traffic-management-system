"""In-process publish/subscribe used to fan events out to WebSocket clients.

Services publish without knowing who is listening, which keeps the controller
and detector free of any transport concerns. Each subscriber owns a bounded
queue: a slow or stalled client drops its oldest messages rather than growing
memory without limit or blocking the publisher.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from ..models.traffic_models import WebSocketEnvelope
from .logger import get_application_logger

logger = get_application_logger("events")

#: Messages buffered per subscriber before the oldest are discarded.
DEFAULT_QUEUE_SIZE = 64


class EventBus:
    """Fan-out of :class:`WebSocketEnvelope` messages to many subscribers."""

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._subscribers: set[asyncio.Queue[WebSocketEnvelope]] = set()
        self._queue_size = queue_size
        self._dropped_messages = 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def dropped_messages(self) -> int:
        """Messages discarded because a subscriber could not keep up."""
        return self._dropped_messages

    def publish(self, event_type: str, data: Any) -> None:
        """Queue an event for every subscriber. Never blocks, never raises."""
        if not self._subscribers:
            return

        envelope = WebSocketEnvelope(type=event_type, data=data)
        for queue in list(self._subscribers):
            self._offer(queue, envelope)

    def _offer(self, queue: asyncio.Queue[WebSocketEnvelope], envelope: WebSocketEnvelope) -> None:
        try:
            queue.put_nowait(envelope)
        except asyncio.QueueFull:
            # Drop the oldest message so the newest state still gets through --
            # for a live dashboard, freshness beats completeness.
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
                self._dropped_messages += 1
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(envelope)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[WebSocketEnvelope]]:
        """Register a subscriber for the lifetime of the ``async with`` block."""
        queue: asyncio.Queue[WebSocketEnvelope] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    async def stream(self) -> AsyncIterator[WebSocketEnvelope]:
        """Yield events as they arrive, until the consumer stops iterating."""
        async with self.subscribe() as queue:
            while True:
                yield await queue.get()

    def clear(self) -> None:
        self._subscribers.clear()
        self._dropped_messages = 0


#: Application-wide bus.
event_bus = EventBus()
