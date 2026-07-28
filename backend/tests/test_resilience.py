"""Resilience tests.

A traffic controller that crashes is worse than one that degrades. These tests
cover what happens when dependencies fail: no model, no database, a hostile
subscriber, a flood of events, concurrent writers.
"""

from __future__ import annotations

import asyncio

from app.core.database import Database
from app.core.events import EventBus
from app.models.traffic_models import (
    EmergencyAlert,
    EmergencyType,
    LaneDirection,
    SignalPhase,
)
from app.services.container import ServiceContainer
from app.services.hardware_bridge import HardwareBridge
from app.services.intelligent_vehicle_detector import IntelligentVehicleDetector


class TestEventBus:
    async def test_publishing_with_no_subscribers_is_a_no_op(self):
        bus = EventBus()
        bus.publish("anything", {"value": 1})  # must not raise

    async def test_every_subscriber_receives_the_event(self):
        bus = EventBus()

        async with bus.subscribe() as first, bus.subscribe() as second:
            bus.publish("phase_change", {"phase": "all_red"})

            assert (await first.get()).type == "phase_change"
            assert (await second.get()).type == "phase_change"

    async def test_a_slow_subscriber_drops_old_events_rather_than_growing(self):
        """An unbounded queue behind a stalled dashboard would leak memory
        until the process died."""
        bus = EventBus(queue_size=4)

        async with bus.subscribe() as queue:
            for index in range(50):
                bus.publish("tick", {"index": index})

            assert queue.qsize() <= 4
            assert bus.dropped_messages > 0

            # The newest event survives: freshness beats completeness.
            latest = None
            while not queue.empty():
                latest = queue.get_nowait()
            assert latest.data["index"] == 49

    async def test_unsubscribing_removes_the_queue(self):
        bus = EventBus()

        async with bus.subscribe():
            assert bus.subscriber_count == 1
        assert bus.subscriber_count == 0

    async def test_publish_never_blocks_the_caller(self):
        bus = EventBus(queue_size=1)

        async with bus.subscribe():
            await asyncio.wait_for(
                asyncio.to_thread(lambda: [bus.publish("t", i) for i in range(1000)]), timeout=5
            )


class TestDatabaseDegradation:
    async def test_an_unreachable_database_does_not_stop_the_app(self, monkeypatch):
        from app.core import database as database_module

        monkeypatch.setattr(database_module.settings, "persistence_enabled", True)
        monkeypatch.setattr(
            database_module.settings, "database_url", "postgresql+asyncpg://nobody@127.0.0.1:1/none"
        )

        db = Database()
        await db.connect()  # must not raise

        assert db.is_available is False

    async def test_sessions_yield_none_when_unavailable(self):
        db = Database()

        async with db.session() as session:
            assert session is None

    async def test_queries_return_empty_results_when_unavailable(self):
        db = Database()
        assert await db.recent_detections() == []
        assert await db.prune_old_records() == 0

    def test_credentials_are_stripped_before_logging(self):
        safe = Database._safe_url("postgresql+asyncpg://user:hunter2@db.internal:5432/traffic")

        assert "hunter2" not in safe
        assert "user" not in safe
        assert "db.internal:5432/traffic" in safe


class TestContainerDegradation:
    async def test_a_failing_service_is_recorded_but_does_not_abort_startup(self, monkeypatch):
        async def explode(self) -> None:
            raise RuntimeError("no model weights on disk")

        monkeypatch.setattr(IntelligentVehicleDetector, "initialize", explode)

        container = ServiceContainer()
        await container.startup()

        try:
            assert container.detector is None
            assert "vehicle_detector" in container.startup_errors

            # Everything else must still be usable.
            health = {service.name: service.ready for service in container.health()}
            assert health["traffic_network"] is True
            assert health["analytics"] is True
            assert health["vehicle_detector"] is False
        finally:
            await container.shutdown()

    async def test_health_explains_why_a_service_is_down(self, monkeypatch):
        async def explode(self) -> None:
            raise RuntimeError("weights download failed")

        monkeypatch.setattr(IntelligentVehicleDetector, "initialize", explode)

        container = ServiceContainer()
        await container.startup()
        try:
            detector_health = next(s for s in container.health() if s.name == "vehicle_detector")
            assert "weights download failed" in (detector_health.detail or "")
        finally:
            await container.shutdown()

    async def test_shutdown_is_idempotent(self):
        container = ServiceContainer()
        await container.startup()

        await container.shutdown()
        await container.shutdown()  # must not raise


class TestHardwareBridge:
    def test_is_inert_when_no_endpoint_is_configured(self):
        bridge = HardwareBridge()

        assert bridge.enabled is False
        # A disabled bridge is healthy: nothing is broken.
        assert bridge.is_ready() is True

    async def test_publishing_while_disabled_is_a_no_op(self, controller):
        bridge = HardwareBridge()
        bridge.publish_state(await controller.get_current_status())  # must not raise

    async def test_builds_a_compact_wire_format_for_microcontrollers(self, controller):
        command = HardwareBridge.build_command(await controller.get_current_status())

        assert set(command["signals"]) == {"north", "south", "east", "west"}
        # e.g. "E:R0,N:G30,S:G30,W:R0"
        assert command["compact"].count(",") == 3
        for part in command["compact"].split(","):
            assert part.split(":")[0] in {"N", "S", "E", "W"}

    def test_health_reports_delivery_statistics(self):
        health = HardwareBridge().health()
        assert {"enabled", "pending", "sent", "failed", "dropped"} <= set(health)

    async def test_hardware_is_driven_even_with_no_dashboard_connected(self, monkeypatch):
        """Physical signals must not depend on somebody watching a dashboard.

        The broadcast loop once skipped the entire tick when no WebSocket client
        was subscribed, so closing the last browser tab stopped commands
        reaching the field device.
        """
        from app.core.config import settings as app_settings
        from app.core.events import event_bus

        monkeypatch.setattr(app_settings, "hardware_webhook_url", "http://field.local/signals")
        monkeypatch.setattr(app_settings, "websocket_broadcast_interval_seconds", 0.01)

        container = ServiceContainer()
        await container.startup()

        try:
            assert event_bus.subscriber_count == 0, "no dashboard should be connected"

            published: list[dict] = []
            assert container.hardware is not None
            monkeypatch.setattr(container.hardware, "publish_state", published.append)

            await asyncio.sleep(0.15)

            assert published, "hardware received nothing while no dashboard was open"
        finally:
            await container.shutdown()


class TestConcurrency:
    async def test_concurrent_count_updates_do_not_corrupt_state(self, controller):
        await asyncio.gather(
            *(controller.update_vehicle_counts({LaneDirection.NORTH: index}) for index in range(50))
        )

        counts = controller.status.vehicle_counts
        assert counts[LaneDirection.NORTH] >= 0
        assert controller.status.total_vehicles == sum(counts.values())

    async def test_concurrent_preemptions_leave_one_coherent_phase(self, controller):
        alerts = [
            EmergencyAlert(
                alert_id=f"emg_{index}",
                emergency_type=EmergencyType.AMBULANCE,
                detected_lane=lane,
            )
            for index, lane in enumerate([LaneDirection.NORTH, LaneDirection.EAST, LaneDirection.SOUTH])
        ]

        await asyncio.gather(*(controller.handle_emergency_override(alert) for alert in alerts))

        assert controller.status.current_phase == SignalPhase.EMERGENCY_PREEMPTION
        greens = [
            lane
            for lane, signal in controller.status.traffic_signals.items()
            if signal.current_state.value == "green"
        ]
        assert len(greens) <= 1, "pre-emption must never open more than one approach"

    async def test_many_pedestrian_requests_are_all_tracked(self, controller):
        await asyncio.gather(
            *(controller.request_pedestrian_crossing(LaneDirection.NORTH) for _ in range(30))
        )
        assert len(controller.pending_pedestrian_requests) == 30

    async def test_the_control_loop_survives_a_burst_of_updates(self, controller):
        await controller.start_simulation()
        try:
            for index in range(100):
                await controller.update_vehicle_counts({LaneDirection.NORTH: index % 20})

            await asyncio.sleep(0.05)
            assert controller.is_running is True
        finally:
            await controller.stop_simulation()


class TestExtremeInputs:
    async def test_absurd_queue_lengths_stay_within_the_green_cap(self, controller, signal_plan_defaults):
        from app.core.config import settings

        await controller.update_vehicle_counts({LaneDirection.NORTH: 1_000_000})
        duration = controller._adaptive_green_duration(SignalPhase.NORTH_SOUTH_GREEN)

        assert duration <= settings.maximum_green_duration

    async def test_an_empty_count_payload_is_accepted(self, controller):
        await controller.update_vehicle_counts({})
        assert controller.status.total_vehicles == 0

    async def test_unknown_lane_keys_are_ignored(self, controller):
        await controller.update_vehicle_counts({LaneDirection.UNKNOWN: 99})
        assert LaneDirection.UNKNOWN not in controller.status.vehicle_counts

    async def test_average_wait_is_zero_with_no_traffic(self, controller):
        await controller.update_vehicle_counts(dict.fromkeys(LaneDirection, 0))
        assert controller.status.average_wait_time == 0.0
