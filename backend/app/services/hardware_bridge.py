"""Bridge between the software controller and physical signal hardware.

Without this the system is only ever a simulation. Configure
``TRAFFIC_HARDWARE_WEBHOOK_URL`` and every phase change is POSTed to a
controller, PLC, relay board or the bundled Arduino gateway
(``Traffic_signal.ino``), which drives the actual lamps.

Delivery is best-effort and asynchronous: a slow or offline field device must
never stall the control loop. Failures are counted and surfaced on the health
endpoint so a dead link is visible rather than silent.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import httpx

from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import IntersectionStatus, TrafficSignalState

#: Compact wire encoding for microcontrollers with little parsing budget.
_STATE_CODES: dict[TrafficSignalState, str] = {
    TrafficSignalState.RED: "R",
    TrafficSignalState.YELLOW: "Y",
    TrafficSignalState.GREEN: "G",
    TrafficSignalState.FLASHING_RED: "FR",
    TrafficSignalState.FLASHING_YELLOW: "FY",
    TrafficSignalState.OFF: "O",
}

#: Queue depth before the oldest pending command is dropped.
_MAX_PENDING_COMMANDS = 32


class HardwareBridge(LoggerMixin):
    """Pushes signal state to field hardware over HTTP."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAX_PENDING_COMMANDS)
        self._worker: asyncio.Task[None] | None = None
        self._ready = False
        self.stats = {"sent": 0, "failed": 0, "dropped": 0, "last_error": None}

    @property
    def enabled(self) -> bool:
        return bool(settings.hardware_webhook_url)

    def is_ready(self) -> bool:
        # A disabled bridge is "ready" in the sense that nothing is broken.
        return self._ready or not self.enabled

    async def initialize(self) -> None:
        if not self.enabled:
            self.logger.info("Hardware bridge disabled (TRAFFIC_HARDWARE_WEBHOOK_URL is unset)")
            return

        headers = {"Content-Type": "application/json"}
        if settings.hardware_webhook_token:
            headers["Authorization"] = f"Bearer {settings.hardware_webhook_token}"

        self._client = httpx.AsyncClient(
            timeout=settings.hardware_webhook_timeout_seconds,
            headers=headers,
        )
        self._worker = asyncio.create_task(self._drain_queue())
        self._ready = True
        self.logger.info("Hardware bridge active -> %s", settings.hardware_webhook_url)

    async def cleanup(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker

        if self._client is not None:
            await self._client.aclose()
            self._client = None

        self._ready = False

    # --- publishing ----------------------------------------------------------
    def publish_state(self, status: IntersectionStatus) -> None:
        """Queue the current signal state for delivery. Never blocks."""
        if not self.enabled or not self._ready:
            return

        command = self.build_command(status)
        try:
            self._queue.put_nowait(command)
        except asyncio.QueueFull:
            # Field hardware only cares about the newest state, so shed the
            # oldest command rather than delaying the freshest one.
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self.stats["dropped"] += 1
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(command)

    @staticmethod
    def build_command(status: IntersectionStatus) -> dict[str, Any]:
        """Wire format sent to the field device."""
        return {
            "intersection_id": status.intersection_id,
            "phase": status.current_phase.value,
            "emergency": status.emergency_mode_active,
            "pedestrian": status.pedestrian_phase_active,
            "timestamp": status.last_updated.isoformat(),
            "signals": {
                lane.value: {
                    "state": _STATE_CODES.get(signal.current_state, "R"),
                    "remaining_seconds": signal.remaining_time,
                }
                for lane, signal in status.traffic_signals.items()
            },
            # Single-line form for microcontrollers that cannot afford a JSON parser,
            # e.g. "N:G30,S:G30,E:R30,W:R30".
            "compact": ",".join(
                f"{lane.value[0].upper()}:{_STATE_CODES.get(signal.current_state, 'R')}{signal.remaining_time}"
                for lane, signal in sorted(status.traffic_signals.items(), key=lambda item: item[0].value)
            ),
        }

    async def _drain_queue(self) -> None:
        """Deliver queued commands until cancelled."""
        while True:
            command = await self._queue.get()
            try:
                await self._deliver(command)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # pragma: no cover - defensive
                self.log_error_with_context(error, "hardware_bridge_worker")
            finally:
                self._queue.task_done()

    async def _deliver(self, command: dict[str, Any]) -> None:
        if self._client is None:
            return

        try:
            response = await self._client.post(settings.hardware_webhook_url, json=command)
            response.raise_for_status()
            self.stats["sent"] += 1
        except httpx.HTTPError as error:
            self.stats["failed"] += 1
            self.stats["last_error"] = str(error)
            # Log at warning, not error: a flaky field link is expected and the
            # next phase change supersedes this command anyway.
            self.logger.warning("Hardware delivery failed: %s", error)

    def health(self) -> dict[str, Any]:
        """Delivery statistics for the health endpoint."""
        return {
            "enabled": self.enabled,
            "endpoint": settings.hardware_webhook_url or None,
            "pending": self._queue.qsize(),
            **self.stats,
        }
