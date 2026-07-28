"""Signal controller tests.

The most important assertions here are the safety invariants: no matter what
sequence of demand, pre-emptions and pedestrian requests arrives, conflicting
movements must never hold green simultaneously, and a green must always be
separated from the conflicting green by yellow and all-red intervals.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.traffic_models import (
    APPROACH_DIRECTIONS,
    EmergencyAlert,
    EmergencyType,
    LaneDirection,
    LaneStatistics,
    SignalPhase,
    SignalPlanUpdate,
    TrafficSignalState,
)
from app.services.adaptive_traffic_manager import AdaptiveTrafficManager

NORTH_SOUTH = {LaneDirection.NORTH, LaneDirection.SOUTH}
EAST_WEST = {LaneDirection.EAST, LaneDirection.WEST}


def green_lanes(controller: AdaptiveTrafficManager) -> set[LaneDirection]:
    return {
        lane
        for lane, signal in controller.status.traffic_signals.items()
        if signal.current_state == TrafficSignalState.GREEN
    }


def assert_no_conflicting_greens(controller: AdaptiveTrafficManager) -> None:
    """North-south and east-west must never be green at the same time."""
    greens = green_lanes(controller)
    assert not (greens & NORTH_SOUTH and greens & EAST_WEST), (
        f"Conflicting greens in phase {controller.status.current_phase}: {greens}"
    )


class TestInitialisation:
    async def test_creates_a_signal_head_per_approach(self, controller):
        assert set(controller.status.traffic_signals) == set(APPROACH_DIRECTIONS)
        assert controller.is_ready()

    async def test_opens_on_north_south_green(self, controller):
        assert controller.status.current_phase == SignalPhase.NORTH_SOUTH_GREEN
        assert green_lanes(controller) == NORTH_SOUTH

    async def test_is_not_running_until_started(self, controller):
        assert controller.is_running is False


class TestPhaseSequence:
    async def test_green_is_followed_by_yellow_then_all_red(self, controller):
        controller._phase_remaining = 0
        controller._tick(1)
        assert controller.status.current_phase == SignalPhase.NORTH_SOUTH_YELLOW
        assert green_lanes(controller) == set()

        controller._phase_remaining = 0
        controller._tick(1)
        assert controller.status.current_phase == SignalPhase.ALL_RED
        assert green_lanes(controller) == set()

    async def test_right_of_way_alternates_between_phases(self, controller):
        # Green -> yellow -> all red -> opposite green.
        for _ in range(3):
            controller._phase_remaining = 0
            controller._tick(1)

        assert controller.status.current_phase == SignalPhase.EAST_WEST_GREEN
        assert green_lanes(controller) == EAST_WEST

    async def test_never_shows_conflicting_greens_over_many_transitions(self, controller):
        for _ in range(200):
            assert_no_conflicting_greens(controller)
            controller._tick(1)
        assert_no_conflicting_greens(controller)

    async def test_completes_a_cycle_after_both_phases(self, controller):
        assert controller.status.cycles_completed == 0

        # Six boundaries: NS green/yellow/all-red, EW green/yellow/all-red.
        for _ in range(6):
            controller._phase_remaining = 0
            controller._tick(1)

        assert controller.status.cycles_completed == 1

    async def test_all_red_clearance_is_honoured(self, controller, signal_plan_defaults):
        settings.all_red_clearance_duration = 4

        controller._enter_phase(SignalPhase.ALL_RED)
        assert controller._phase_remaining == 4
        assert all(
            signal.current_state == TrafficSignalState.RED
            for signal in controller.status.traffic_signals.values()
        )


class TestAdaptiveTiming:
    async def test_empty_approach_gets_the_minimum_green(self, controller, signal_plan_defaults):
        settings.minimum_green_duration = 8
        duration = controller._adaptive_green_duration(SignalPhase.NORTH_SOUTH_GREEN)
        assert duration == 8

    async def test_green_grows_with_the_queue(self, controller, lane_statistics, signal_plan_defaults):
        settings.minimum_green_duration = 10
        settings.maximum_green_duration = 120
        settings.seconds_per_queued_vehicle = 2.0

        await controller.update_vehicle_counts(
            {lane: stats.vehicle_count for lane, stats in lane_statistics.items()},
            lane_statistics,
        )

        busy = controller._adaptive_green_duration(SignalPhase.NORTH_SOUTH_GREEN)
        quiet = controller._adaptive_green_duration(SignalPhase.EAST_WEST_GREEN)

        assert busy > quiet
        # 10 + (14.0 + 9.5) * 2.0 = 57
        assert busy == 57

    async def test_green_is_capped_so_one_approach_cannot_starve_the_others(
        self, controller, signal_plan_defaults
    ):
        settings.maximum_green_duration = 45

        await controller.update_vehicle_counts(
            {LaneDirection.NORTH: 500, LaneDirection.SOUTH: 500},
            {
                LaneDirection.NORTH: LaneStatistics(
                    lane=LaneDirection.NORTH, vehicle_count=500, passenger_car_units=600.0
                )
            },
        )

        assert controller._adaptive_green_duration(SignalPhase.NORTH_SOUTH_GREEN) == 45

    async def test_fixed_time_mode_ignores_demand(self, controller, lane_statistics, signal_plan_defaults):
        settings.default_green_signal_duration = 30
        controller.status.adaptive_mode = False

        await controller.update_vehicle_counts(
            {lane: stats.vehicle_count for lane, stats in lane_statistics.items()},
            lane_statistics,
        )

        assert controller._adaptive_green_duration(SignalPhase.NORTH_SOUTH_GREEN) == 30

    async def test_serving_a_phase_discharges_its_queue(self, controller, lane_statistics):
        await controller.update_vehicle_counts(
            {lane: stats.vehicle_count for lane, stats in lane_statistics.items()},
            lane_statistics,
        )
        before = controller.status.vehicle_counts[LaneDirection.NORTH]

        controller._enter_phase(SignalPhase.NORTH_SOUTH_GREEN)

        assert controller.status.vehicle_counts[LaneDirection.NORTH] < before

    async def test_counts_never_go_negative(self, controller):
        await controller.update_vehicle_counts({LaneDirection.NORTH: 1})
        for _ in range(20):
            controller._enter_phase(SignalPhase.NORTH_SOUTH_GREEN)

        assert all(count >= 0 for count in controller.status.vehicle_counts.values())


class TestEmergencyPreemption:
    def build_alert(self, lane: LaneDirection = LaneDirection.NORTH, **kwargs) -> EmergencyAlert:
        return EmergencyAlert(
            alert_id=kwargs.pop("alert_id", "emg_test"),
            emergency_type=EmergencyType.AMBULANCE,
            detected_lane=lane,
            **kwargs,
        )

    async def test_accepts_a_validated_alert_model(self, controller):
        """The API used to hand the controller a raw dict, which crashed on
        ``alert.alert_id``. It must receive a validated model."""
        alert = self.build_alert()
        result = await controller.handle_emergency_override(alert)

        assert result.alert_id == "emg_test"
        assert controller.status.emergency_mode_active is True

    async def test_gives_only_the_emergency_approach_green(self, controller):
        await controller.handle_emergency_override(self.build_alert(LaneDirection.EAST))

        assert controller.status.current_phase == SignalPhase.EMERGENCY_PREEMPTION
        assert green_lanes(controller) == {LaneDirection.EAST}

    async def test_preemption_does_not_create_conflicting_greens(self, controller):
        await controller.handle_emergency_override(self.build_alert(LaneDirection.WEST))
        assert_no_conflicting_greens(controller)

    async def test_highest_priority_alert_wins(self, controller):
        await controller.handle_emergency_override(
            self.build_alert(LaneDirection.NORTH, alert_id="low", priority_level=2)
        )
        await controller.handle_emergency_override(
            self.build_alert(LaneDirection.EAST, alert_id="high", priority_level=5)
        )

        assert controller._highest_priority_alert().alert_id == "high"

    async def test_clearing_the_last_alert_leaves_emergency_mode(self, controller):
        await controller.handle_emergency_override(self.build_alert())
        assert await controller.clear_emergency_override("emg_test") is True

        assert controller.status.emergency_mode_active is False
        assert controller.status.current_phase != SignalPhase.EMERGENCY_PREEMPTION

    async def test_clearing_an_unknown_alert_reports_false(self, controller):
        assert await controller.clear_emergency_override("nope") is False

    async def test_expired_alerts_are_dropped_on_tick(self, controller):
        alert = self.build_alert(override_duration=1)
        await controller.handle_emergency_override(alert)

        # Backdate creation so the override window has already elapsed.
        object.__setattr__(alert, "created_at", alert.created_at.replace(year=2020))
        controller._tick(1)

        assert controller.status.emergency_mode_active is False
        assert controller.active_emergency_alerts == []


class TestPedestrians:
    async def test_a_request_is_recorded_as_pending(self, controller):
        request = await controller.request_pedestrian_crossing(LaneDirection.NORTH, 2)

        assert request.is_served is False
        assert len(controller.pending_pedestrian_requests) == 1

    async def test_pending_requests_are_served_at_the_next_all_red(self, controller):
        await controller.request_pedestrian_crossing(LaneDirection.NORTH)

        controller._enter_phase(SignalPhase.ALL_RED)
        controller._phase_remaining = 0
        controller._tick(1)

        assert controller.status.current_phase == SignalPhase.PEDESTRIAN_CROSSING
        assert green_lanes(controller) == set(), "vehicles must be held during the walk phase"

    async def test_the_walk_phase_marks_requests_served(self, controller):
        await controller.request_pedestrian_crossing(LaneDirection.NORTH)
        controller._enter_phase(SignalPhase.PEDESTRIAN_CROSSING)

        controller._phase_remaining = 0
        controller._tick(1)

        assert controller.pending_pedestrian_requests == []

    async def test_accessibility_requests_get_a_longer_walk(self, controller, signal_plan_defaults):
        settings.pedestrian_crossing_duration = 10

        await controller.request_pedestrian_crossing(LaneDirection.NORTH, accessibility_extension=True)
        assert controller._pedestrian_phase_duration() == 15

    async def test_a_long_wait_preempts_the_running_vehicle_phase(self, controller, signal_plan_defaults):
        settings.pedestrian_max_wait_seconds = 30

        first = await controller.request_pedestrian_crossing(LaneDirection.NORTH)
        object.__setattr__(first, "requested_at", first.requested_at.replace(year=2020))

        controller._enter_phase(SignalPhase.NORTH_SOUTH_GREEN)
        await controller.request_pedestrian_crossing(LaneDirection.SOUTH)

        assert controller.status.current_phase == SignalPhase.PEDESTRIAN_CROSSING


class TestPlanUpdates:
    async def test_applies_only_the_supplied_fields(self, controller, signal_plan_defaults):
        applied = await controller.apply_plan_update(
            SignalPlanUpdate(minimum_green_duration=15, adaptive_mode=False)
        )

        assert applied == {"adaptive_mode": False, "minimum_green_duration": 15}
        assert settings.minimum_green_duration == 15
        assert controller.status.adaptive_mode is False

    async def test_rejects_an_inconsistent_plan(self, controller, signal_plan_defaults):
        with pytest.raises(ValueError, match="cannot exceed"):
            await controller.apply_plan_update(
                SignalPlanUpdate(minimum_green_duration=200, maximum_green_duration=30)
            )


class TestLifecycle:
    async def test_start_then_stop_leaves_no_running_task(self, controller):
        await controller.start_simulation()
        assert controller.is_running is True

        await controller.stop_simulation()
        assert controller.is_running is False
        assert controller._control_task is None

    async def test_starting_twice_is_harmless(self, controller):
        await controller.start_simulation()
        await controller.start_simulation()
        assert controller.is_running is True
        await controller.stop_simulation()

    async def test_stopping_when_never_started_is_harmless(self, controller):
        await controller.stop_simulation()
        assert controller.is_running is False


class TestEventEmission:
    async def test_emits_phase_changes(self):
        captured: list[tuple[str, object]] = []
        manager = AdaptiveTrafficManager(
            intersection_id="events", on_event=lambda kind, payload: captured.append((kind, payload))
        )
        await manager.initialize()

        assert any(kind == "phase_change" for kind, _ in captured)
        await manager.cleanup()

    async def test_a_failing_subscriber_cannot_break_the_controller(self):
        def explode(_kind: str, _payload: object) -> None:
            raise RuntimeError("subscriber is broken")

        manager = AdaptiveTrafficManager(intersection_id="hostile", on_event=explode)
        await manager.initialize()  # must not raise

        assert manager.is_ready()
        await manager.cleanup()
