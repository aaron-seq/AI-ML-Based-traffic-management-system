"""Service container: owns construction, startup order and shutdown.

Keeping wiring in one place means ``main.py`` stays a thin ASGI shell and the
route modules depend on an interface rather than on module-level globals. Each
service starts independently and a failure degrades that capability only -- a
missing model must not take the signal controller offline with it.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..core.database import database
from ..core.events import event_bus
from ..core.logger import get_application_logger
from ..models.traffic_models import ServiceHealth
from .analytics_service import TrafficAnalyticsService
from .forecast_service import TrafficForecastService
from .hardware_bridge import HardwareBridge
from .impact_service import TrafficImpactService
from .intelligent_vehicle_detector import IntelligentVehicleDetector
from .network_coordinator import TrafficNetwork

logger = get_application_logger("container")

#: Directories the application writes to at runtime.
_RUNTIME_DIRECTORIES = ("./uploads", "./output_images", "./logs", "./models", "./data")


class ServiceContainer:
    """Holds every long-lived service and manages its lifecycle."""

    def __init__(self) -> None:
        self.detector: IntelligentVehicleDetector | None = None
        self.network: TrafficNetwork | None = None
        self.analytics: TrafficAnalyticsService | None = None
        self.forecast: TrafficForecastService | None = None
        self.impact: TrafficImpactService | None = None
        self.hardware: HardwareBridge | None = None

        self.started_at = time.monotonic()
        self.startup_errors: dict[str, str] = {}
        self._broadcast_task: asyncio.Task[None] | None = None
        #: Strong references to in-flight fire-and-forget writes.
        self._pending_writes: set[asyncio.Task[None]] = set()

    # --- startup -------------------------------------------------------------
    async def startup(self) -> None:
        """Initialise every service, tolerating individual failures."""
        self.started_at = time.monotonic()
        self._create_runtime_directories()

        await database.connect()

        # The controller network is the core of the system: publish its events
        # onto the bus so WebSocket clients and analytics both see them.
        self.network = TrafficNetwork(on_event=self._on_controller_event)
        await self._start("traffic_network", self.network.initialize())

        self.analytics = TrafficAnalyticsService()
        await self._start("analytics", self.analytics.initialize())

        self.forecast = TrafficForecastService()
        await self._start("forecast", self.forecast.initialize())

        self.impact = TrafficImpactService()
        await self._start("impact", self.impact.initialize())

        self.hardware = HardwareBridge()
        await self._start("hardware_bridge", self.hardware.initialize())

        # Detection is the slowest to start and the most likely to fail (weights
        # download, no disk, no GPU), so it goes last and never blocks the rest.
        self.detector = IntelligentVehicleDetector()
        if not await self._start("vehicle_detector", self.detector.initialize()):
            self.detector = None

        if self.network is not None:
            await self.network.start_all()
            self._broadcast_task = asyncio.create_task(self._broadcast_status_loop())

        logger.info(
            "Startup complete: %d/%d services ready",
            sum(1 for service in self.health() if service.ready),
            len(self.health()),
        )

    async def _start(self, name: str, coroutine: Any) -> bool:
        """Await a service's initialiser, recording any failure."""
        try:
            await coroutine
            logger.info("Service ready: %s", name)
            return True
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            self.startup_errors[name] = message
            logger.error("Service failed to start: %s (%s)", name, message, exc_info=True)
            return False

    @staticmethod
    def _create_runtime_directories() -> None:
        for directory in _RUNTIME_DIRECTORIES:
            try:
                Path(directory).mkdir(parents=True, exist_ok=True)
            except OSError as error:
                logger.warning("Could not create %s: %s", directory, error)

    # --- shutdown ------------------------------------------------------------
    async def shutdown(self) -> None:
        """Stop everything in reverse dependency order."""
        task = self._broadcast_task
        self._broadcast_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        for name, service in (
            ("vehicle_detector", self.detector),
            ("hardware_bridge", self.hardware),
            ("impact", self.impact),
            ("forecast", self.forecast),
            ("analytics", self.analytics),
            ("traffic_network", self.network),
        ):
            if service is None:
                continue
            try:
                await service.cleanup()
            except Exception as error:
                logger.error("Error shutting down %s: %s", name, error)

        await database.disconnect()
        event_bus.clear()
        logger.info("Shutdown complete")

    # --- event plumbing ------------------------------------------------------
    def _on_controller_event(self, event_type: str, payload: Any) -> None:
        """Fan controller events out to WebSocket clients and analytics."""
        event_bus.publish(event_type, payload)

        if self.analytics is not None and isinstance(payload, dict):
            intersection_id = payload.get("intersection_id", "main_intersection")
            # Fire-and-forget: persistence must not block the control loop. The
            # task is kept in a set until it finishes -- asyncio holds only a
            # weak reference, so an unreferenced task can be collected mid-flight
            # and the write silently lost.
            task = asyncio.create_task(self.analytics.record_event(event_type, payload, intersection_id))
            self._pending_writes.add(task)
            task.add_done_callback(self._pending_writes.discard)

    async def _broadcast_status_loop(self) -> None:
        """Publish intersection state to dashboards and to field hardware.

        These two consumers are deliberately decoupled. An earlier version
        skipped the whole tick when no WebSocket client was connected, which
        meant physical signals stopped receiving commands the moment the last
        dashboard tab was closed -- the lamps would hold their last state, or
        drop to the device's failsafe, purely because nobody was watching.
        Hardware delivery must never depend on an observer.
        """
        interval = settings.websocket_broadcast_interval_seconds
        try:
            while True:
                await asyncio.sleep(interval)
                if self.network is None:
                    continue

                # Skip only the serialisation when nobody is watching; the
                # hardware push below still runs.
                serialise_for_dashboards = event_bus.subscriber_count > 0

                for controller in self.network.controllers:
                    status = await controller.get_current_status()

                    if serialise_for_dashboards:
                        event_bus.publish("intersection_status", status.model_dump(mode="json"))

                    if self.hardware is not None:
                        self.hardware.publish_state(status)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # pragma: no cover - defensive
            logger.error("Status broadcast loop stopped: %s", error, exc_info=True)

    # --- reporting -----------------------------------------------------------
    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def health(self) -> list[ServiceHealth]:
        """Readiness of every service, for the health endpoint."""
        checks: list[ServiceHealth] = []

        for name, service in (
            ("vehicle_detector", self.detector),
            ("traffic_network", self.network),
            ("analytics", self.analytics),
            ("forecast", self.forecast),
            ("impact", self.impact),
            ("hardware_bridge", self.hardware),
        ):
            if service is None:
                checks.append(
                    ServiceHealth(
                        name=name,
                        ready=False,
                        detail=self.startup_errors.get(name, "Service not initialised"),
                    )
                )
            else:
                ready = service.is_ready()
                checks.append(
                    ServiceHealth(
                        name=name,
                        ready=ready,
                        detail=None if ready else self.startup_errors.get(name, "Not ready"),
                    )
                )

        checks.append(
            ServiceHealth(
                name="persistence",
                ready=database.is_available,
                detail=None
                if database.is_available
                else "Disabled or unreachable; history is in-memory only",
            )
        )
        return checks


#: Application-wide container, populated during the FastAPI lifespan.
container = ServiceContainer()
