"""Adaptive signal control for a single intersection.

The controller is a phase-based state machine. Right of way belongs to a
*phase*, never to individual signal heads, which makes conflicting greens
structurally impossible:

    NS green -> NS yellow -> all-red -> EW green -> EW yellow -> all-red -> ...

Pedestrian and emergency phases are inserted at all-red boundaries, so a
pre-emption can never cut straight from one green to a conflicting green
without the intervening yellow and clearance intervals.

Green durations adapt to measured demand: each phase gets a minimum green plus
an allowance per queued passenger-car unit, clamped to a configured maximum so
one busy approach cannot starve the others.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from ..core import metrics
from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import (
    APPROACH_DIRECTIONS,
    EmergencyAlert,
    IntersectionStatus,
    LaneDirection,
    LaneStatistics,
    PedestrianRequest,
    SignalPhase,
    SignalPlanUpdate,
    TrafficSignal,
    TrafficSignalState,
    utc_now,
)

#: Which approaches hold right of way in each vehicle phase.
_PHASE_MOVEMENTS: dict[SignalPhase, tuple[LaneDirection, ...]] = {
    SignalPhase.NORTH_SOUTH_GREEN: (LaneDirection.NORTH, LaneDirection.SOUTH),
    SignalPhase.NORTH_SOUTH_YELLOW: (LaneDirection.NORTH, LaneDirection.SOUTH),
    SignalPhase.EAST_WEST_GREEN: (LaneDirection.EAST, LaneDirection.WEST),
    SignalPhase.EAST_WEST_YELLOW: (LaneDirection.EAST, LaneDirection.WEST),
}

#: Vehicle phases in cycle order; a full pass through both is one cycle.
_GREEN_PHASES: tuple[SignalPhase, ...] = (
    SignalPhase.NORTH_SOUTH_GREEN,
    SignalPhase.EAST_WEST_GREEN,
)

_YELLOW_FOR_GREEN: dict[SignalPhase, SignalPhase] = {
    SignalPhase.NORTH_SOUTH_GREEN: SignalPhase.NORTH_SOUTH_YELLOW,
    SignalPhase.EAST_WEST_GREEN: SignalPhase.EAST_WEST_YELLOW,
}

#: Saturation flow: vehicles that clear a lane per second of green. ~1900
#: passenger cars per hour of green per lane is the usual planning figure.
SATURATION_FLOW_PER_SECOND = 0.53


class AdaptiveTrafficManager(LoggerMixin):
    """Runs the signal state machine for one intersection."""

    def __init__(
        self,
        intersection_id: str = "main_intersection",
        name: str = "Main Intersection",
        on_event: Callable[[str, Any], None] | None = None,
    ) -> None:
        self.intersection_id = intersection_id
        self.name = name
        self._on_event = on_event

        self.status = IntersectionStatus(intersection_id=intersection_id, name=name)
        self._initialize_signals()

        self._phase_index = 0
        self._phase_remaining = 0
        self._phase_elapsed = 0
        self._green_phases_served = 0

        self._emergency_alerts: dict[str, EmergencyAlert] = {}
        self._pedestrian_requests: dict[str, PedestrianRequest] = {}

        self._control_task: asyncio.Task[None] | None = None
        self._running = False
        self._lock = asyncio.Lock()

        self.performance_metrics: dict[str, Any] = {
            "cycles_completed": 0,
            "emergency_overrides": 0,
            "pedestrian_phases_served": 0,
            "adaptive_adjustments": 0,
            "total_vehicles_served": 0,
            "total_delay_seconds": 0.0,
        }

    # --- lifecycle -----------------------------------------------------------
    def _initialize_signals(self) -> None:
        """Start every head at red; the first tick promotes the opening phase."""
        for lane in APPROACH_DIRECTIONS:
            self.status.traffic_signals[lane] = TrafficSignal(
                signal_id=f"{self.intersection_id}_{lane.value}",
                direction=lane,
                current_state=TrafficSignalState.RED,
                remaining_time=0,
                cycle_duration=settings.default_green_signal_duration,
            )
            self.status.vehicle_counts.setdefault(lane, 0)
            self.status.lane_statistics.setdefault(lane, LaneStatistics(lane=lane))

        self.status.current_phase = SignalPhase.ALL_RED

    async def initialize(self) -> None:
        """Put the intersection into its opening phase."""
        async with self._lock:
            self._enter_phase(SignalPhase.NORTH_SOUTH_GREEN)
        self.logger.info("Intersection %s initialised", self.intersection_id)

    async def start_simulation(self) -> None:
        """Start the control loop."""
        if self._running:
            self.logger.debug("Control loop for %s already running", self.intersection_id)
            return

        self._running = True
        self._control_task = asyncio.create_task(self._control_loop())
        self.logger.info("Control loop started for %s", self.intersection_id)

    async def stop_simulation(self) -> None:
        """Stop the control loop and wait for it to unwind."""
        self._running = False
        task = self._control_task
        self._control_task = None

        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self.logger.info("Control loop stopped for %s", self.intersection_id)

    async def cleanup(self) -> None:
        await self.stop_simulation()
        self._emergency_alerts.clear()
        self._pedestrian_requests.clear()

    def is_ready(self) -> bool:
        return len(self.status.traffic_signals) == len(APPROACH_DIRECTIONS)

    @property
    def is_running(self) -> bool:
        return self._running

    # --- control loop --------------------------------------------------------
    async def _control_loop(self) -> None:
        """Advance the state machine once per tick until stopped."""
        interval = settings.control_loop_interval_seconds
        try:
            while self._running:
                await asyncio.sleep(interval)
                async with self._lock:
                    self._tick(int(interval) or 1)
        except asyncio.CancelledError:
            self.logger.debug("Control loop for %s cancelled", self.intersection_id)
            raise
        except Exception as error:  # pragma: no cover - loop must never die quietly
            self.log_error_with_context(error, "control_loop")
            metrics.record_error(type(error).__name__, "traffic_controller")
            self._running = False

    def _tick(self, seconds: int) -> None:
        """Advance time by ``seconds`` and transition phases when they expire."""
        self._expire_emergency_alerts()

        self._phase_remaining = max(0, self._phase_remaining - seconds)
        self._phase_elapsed += seconds

        for signal in self.status.traffic_signals.values():
            signal.remaining_time = self._phase_remaining
            signal.last_updated = utc_now()

        self.status.phase_elapsed_seconds = self._phase_elapsed
        self.status.last_updated = utc_now()

        if self._phase_remaining <= 0:
            self._advance_phase()

    def _advance_phase(self) -> None:
        """Choose and enter the phase that follows the one just completed."""
        current = self.status.current_phase

        if current == SignalPhase.EMERGENCY_PREEMPTION:
            # Resume normal service; the pre-empted approach keeps its green.
            self._enter_phase(SignalPhase.ALL_RED)
            return

        if current in _YELLOW_FOR_GREEN:
            self._enter_phase(_YELLOW_FOR_GREEN[current])
            return

        if current in (SignalPhase.NORTH_SOUTH_YELLOW, SignalPhase.EAST_WEST_YELLOW):
            self._enter_phase(SignalPhase.ALL_RED)
            return

        if current == SignalPhase.PEDESTRIAN_CROSSING:
            self._complete_pedestrian_phase()
            self._enter_phase(SignalPhase.ALL_RED)
            return

        # Coming out of all-red: serve pedestrians if any are waiting, else the
        # next vehicle phase.
        if self._pending_pedestrian_requests():
            self._enter_phase(SignalPhase.PEDESTRIAN_CROSSING)
            return

        self._phase_index = (self._phase_index + 1) % len(_GREEN_PHASES)
        if self._phase_index == 0:
            self._complete_cycle()
        self._enter_phase(_GREEN_PHASES[self._phase_index])

    def _enter_phase(self, phase: SignalPhase, duration: int | None = None) -> None:
        """Apply signal aspects and timing for ``phase``."""
        self.status.current_phase = phase
        self._phase_elapsed = 0
        self._phase_remaining = duration if duration is not None else self._duration_for(phase)

        aspects = self._aspects_for(phase)
        for lane, signal in self.status.traffic_signals.items():
            signal.current_state = aspects[lane]
            signal.remaining_time = self._phase_remaining
            signal.cycle_duration = max(self._phase_remaining, 1)
            signal.last_updated = utc_now()

        self.status.pedestrian_phase_active = phase == SignalPhase.PEDESTRIAN_CROSSING
        self.status.phase_elapsed_seconds = 0
        self.status.last_updated = utc_now()

        metrics.record_phase_change(self.intersection_id, phase.value)
        if phase in _GREEN_PHASES:
            metrics.record_green_duration(self.intersection_id, self._phase_remaining)
            self._green_phases_served += 1
            self._account_for_served_vehicles(phase, self._phase_remaining)

        self.logger.debug(
            "Intersection %s entered %s for %ds", self.intersection_id, phase.value, self._phase_remaining
        )
        self._emit(
            "phase_change",
            {
                "intersection_id": self.intersection_id,
                "phase": phase.value,
                "duration_seconds": self._phase_remaining,
            },
        )

    def _aspects_for(self, phase: SignalPhase) -> dict[LaneDirection, TrafficSignalState]:
        """The aspect each head shows during ``phase``."""
        aspects = dict.fromkeys(APPROACH_DIRECTIONS, TrafficSignalState.RED)

        if phase in (SignalPhase.NORTH_SOUTH_GREEN, SignalPhase.EAST_WEST_GREEN):
            for lane in _PHASE_MOVEMENTS[phase]:
                aspects[lane] = TrafficSignalState.GREEN
        elif phase in (SignalPhase.NORTH_SOUTH_YELLOW, SignalPhase.EAST_WEST_YELLOW):
            for lane in _PHASE_MOVEMENTS[phase]:
                aspects[lane] = TrafficSignalState.YELLOW
        elif phase == SignalPhase.EMERGENCY_PREEMPTION:
            for lane, alert_lane in self._emergency_lanes():
                aspects[lane] = TrafficSignalState.GREEN if lane == alert_lane else TrafficSignalState.RED
        # ALL_RED and PEDESTRIAN_CROSSING leave every vehicle head red.

        return aspects

    def _emergency_lanes(self) -> Iterable[tuple[LaneDirection, LaneDirection]]:
        """Pair every approach with the approach currently being pre-empted."""
        active = self._highest_priority_alert()
        preempted = active.detected_lane if active else LaneDirection.UNKNOWN
        for lane in APPROACH_DIRECTIONS:
            yield lane, preempted

    def _duration_for(self, phase: SignalPhase) -> int:
        """How long ``phase`` should last, given current demand."""
        if phase in _GREEN_PHASES:
            return self._adaptive_green_duration(phase)
        if phase in (SignalPhase.NORTH_SOUTH_YELLOW, SignalPhase.EAST_WEST_YELLOW):
            return settings.yellow_signal_duration
        if phase == SignalPhase.ALL_RED:
            return settings.all_red_clearance_duration
        if phase == SignalPhase.PEDESTRIAN_CROSSING:
            return self._pedestrian_phase_duration()
        if phase == SignalPhase.EMERGENCY_PREEMPTION:
            active = self._highest_priority_alert()
            return active.override_duration if active else settings.emergency_override_duration
        return settings.default_green_signal_duration

    def _adaptive_green_duration(self, phase: SignalPhase) -> int:
        """Green time proportional to the queue the phase has to discharge.

        Fixed-time control gives every phase the same green regardless of
        demand, which wastes green on empty approaches and under-serves busy
        ones. Here the queue is measured in passenger-car units so that a bus
        is correctly weighted heavier than a motorcycle.
        """
        if not self.status.adaptive_mode:
            return settings.default_green_signal_duration

        queue = sum(
            self.status.lane_statistics[lane].passenger_car_units
            for lane in _PHASE_MOVEMENTS[phase]
            if lane in self.status.lane_statistics
        )

        duration = settings.minimum_green_duration + queue * settings.seconds_per_queued_vehicle
        clamped = round(max(settings.minimum_green_duration, min(duration, settings.maximum_green_duration)))

        if clamped != settings.default_green_signal_duration:
            self.performance_metrics["adaptive_adjustments"] += 1

        return clamped

    def _account_for_served_vehicles(self, phase: SignalPhase, green_seconds: int) -> None:
        """Estimate how much of each queue this green discharges.

        Queues are decremented rather than left to grow unbounded, so counts
        stay meaningful between camera updates.
        """
        capacity = green_seconds * SATURATION_FLOW_PER_SECOND
        for lane in _PHASE_MOVEMENTS[phase]:
            stats = self.status.lane_statistics.get(lane)
            if stats is None:
                continue

            served = min(stats.vehicle_count, int(capacity))
            if served <= 0:
                continue

            self.performance_metrics["total_vehicles_served"] += served
            stats.vehicle_count = max(0, stats.vehicle_count - served)
            stats.passenger_car_units = max(0.0, round(stats.passenger_car_units - served, 2))
            self.status.vehicle_counts[lane] = stats.vehicle_count
            metrics.set_queue_length(self.intersection_id, lane.value, stats.vehicle_count)

        self.status.total_vehicles = sum(self.status.vehicle_counts.values())

    def _complete_cycle(self) -> None:
        self.performance_metrics["cycles_completed"] += 1
        self.status.cycles_completed = self.performance_metrics["cycles_completed"]
        metrics.record_cycle(self.intersection_id)
        self._emit(
            "cycle_completed",
            {
                "intersection_id": self.intersection_id,
                "cycles_completed": self.status.cycles_completed,
            },
        )

    # --- demand input --------------------------------------------------------
    async def update_vehicle_counts(
        self,
        lane_counts: dict[LaneDirection, int],
        lane_statistics: dict[LaneDirection, LaneStatistics] | None = None,
    ) -> None:
        """Feed fresh queue measurements into the controller."""
        async with self._lock:
            for lane in APPROACH_DIRECTIONS:
                count = int(lane_counts.get(lane, 0))
                self.status.vehicle_counts[lane] = count

                stats = (lane_statistics or {}).get(lane)
                if stats is not None:
                    self.status.lane_statistics[lane] = stats
                else:
                    # Without capacity-weighted data, treat every vehicle as one
                    # passenger car -- a safe, slightly conservative assumption.
                    self.status.lane_statistics[lane] = LaneStatistics(
                        lane=lane, vehicle_count=count, passenger_car_units=float(count)
                    )

                metrics.set_queue_length(self.intersection_id, lane.value, count)

            self.status.total_vehicles = sum(self.status.vehicle_counts.values())
            self.status.last_detection_time = utc_now()
            self.status.average_wait_time = self._estimate_average_wait()

            # A queue that appears while the serving phase is already green gets
            # its green extended, up to the configured maximum.
            self._extend_current_green_if_needed()

        self.logger.info("Queues updated at %s: %s", self.intersection_id, dict(self.status.vehicle_counts))

    def _extend_current_green_if_needed(self) -> None:
        """Grant extra green when demand arrives mid-phase."""
        phase = self.status.current_phase
        if phase not in _GREEN_PHASES or not self.status.adaptive_mode:
            return

        target = self._adaptive_green_duration(phase)
        already_used = self._phase_elapsed
        extension = target - already_used - self._phase_remaining

        if extension <= 0:
            return

        headroom = settings.maximum_green_duration - (already_used + self._phase_remaining)
        granted = int(min(extension, max(headroom, 0)))
        if granted <= 0:
            return

        self._phase_remaining += granted
        for signal in self.status.traffic_signals.values():
            signal.remaining_time = self._phase_remaining

        self.performance_metrics["adaptive_adjustments"] += 1
        self.logger.debug("Extended %s green by %ds at %s", phase.value, granted, self.intersection_id)

    def _estimate_average_wait(self) -> float:
        """Average delay per vehicle, from queue length and discharge rate.

        A uniform-arrival approximation: a vehicle joining a queue of ``n``
        waits for the ``n`` ahead of it to discharge, plus the remaining red.
        Good enough for dashboards and impact modelling; it is not a
        substitute for a calibrated microsimulation.
        """
        total_wait = 0.0
        total_vehicles = 0

        for lane, stats in self.status.lane_statistics.items():
            if stats.vehicle_count <= 0:
                continue
            discharge_seconds = stats.passenger_car_units / SATURATION_FLOW_PER_SECOND
            red_wait = 0.0 if self.status.traffic_signals[lane].is_active() else self._phase_remaining
            total_wait += (discharge_seconds / 2 + red_wait) * stats.vehicle_count
            total_vehicles += stats.vehicle_count

        if total_vehicles == 0:
            return 0.0

        average = total_wait / total_vehicles
        self.performance_metrics["total_delay_seconds"] += total_wait
        return round(average, 2)

    # --- emergency pre-emption ----------------------------------------------
    async def handle_emergency_override(self, alert: EmergencyAlert) -> EmergencyAlert:
        """Give an emergency vehicle's approach immediate right of way.

        Accepts a validated :class:`EmergencyAlert`. The previous version was
        handed a raw ``dict`` by the API layer and crashed on ``alert.alert_id``.
        """
        async with self._lock:
            self._emergency_alerts[alert.alert_id] = alert
            self.status.emergency_mode_active = True
            self.performance_metrics["emergency_overrides"] += 1

            self._enter_phase(SignalPhase.EMERGENCY_PREEMPTION, duration=alert.override_duration)

        metrics.record_emergency_override(alert.emergency_type.value, alert.detected_lane.value)
        self.logger.warning(
            "Emergency pre-emption at %s: %s approaching from %s (alert %s)",
            self.intersection_id,
            alert.emergency_type.value,
            alert.detected_lane.value,
            alert.alert_id,
        )
        self._emit("emergency_alert", alert.model_dump(mode="json"))
        return alert

    async def clear_emergency_override(self, alert_id: str) -> bool:
        """Cancel a pre-emption early. Returns whether it was active."""
        async with self._lock:
            alert = self._emergency_alerts.pop(alert_id, None)
            if alert is None:
                return False

            alert.is_active = False
            alert.resolved_at = utc_now()

            if not self._emergency_alerts:
                self.status.emergency_mode_active = False
                if self.status.current_phase == SignalPhase.EMERGENCY_PREEMPTION:
                    self._enter_phase(SignalPhase.ALL_RED)

        self.logger.info("Emergency alert %s cleared at %s", alert_id, self.intersection_id)
        self._emit("emergency_cleared", {"alert_id": alert_id, "intersection_id": self.intersection_id})
        return True

    def _expire_emergency_alerts(self) -> None:
        """Drop alerts whose override window has elapsed."""
        expired = [alert_id for alert_id, alert in self._emergency_alerts.items() if alert.has_expired()]
        for alert_id in expired:
            alert = self._emergency_alerts.pop(alert_id)
            alert.is_active = False
            alert.resolved_at = utc_now()
            self.logger.info("Emergency alert %s expired at %s", alert_id, self.intersection_id)
            self._emit("emergency_cleared", {"alert_id": alert_id, "intersection_id": self.intersection_id})

        if not self._emergency_alerts:
            self.status.emergency_mode_active = False

    def _highest_priority_alert(self) -> EmergencyAlert | None:
        """The alert that should currently control the intersection."""
        active = [alert for alert in self._emergency_alerts.values() if alert.is_active]
        if not active:
            return None
        # Highest priority wins; ties broken by whichever arrived first.
        return max(active, key=lambda alert: (alert.priority_level, -alert.created_at.timestamp()))

    @property
    def active_emergency_alerts(self) -> list[EmergencyAlert]:
        return [alert for alert in self._emergency_alerts.values() if alert.is_active]

    # --- pedestrians ---------------------------------------------------------
    async def request_pedestrian_crossing(
        self, crossing: LaneDirection, pedestrian_count: int = 1, accessibility_extension: bool = False
    ) -> PedestrianRequest:
        """Register a crossing request; it is served at the next all-red."""
        request = PedestrianRequest(
            request_id=str(uuid.uuid4()),
            crossing=crossing,
            pedestrian_count=pedestrian_count,
            accessibility_extension=accessibility_extension,
        )

        async with self._lock:
            self._pedestrian_requests[request.request_id] = request
            self.status.pending_pedestrian_requests = len(self._pending_pedestrian_requests())

            # A request that has waited too long pre-empts the running phase
            # rather than waiting for the cycle to come round again.
            if self._longest_pedestrian_wait() >= settings.pedestrian_max_wait_seconds:
                self._enter_phase(SignalPhase.PEDESTRIAN_CROSSING)

        metrics.record_pedestrian_request(crossing.value)
        self.logger.info(
            "Pedestrian crossing requested at %s for %s (%d waiting)",
            self.intersection_id,
            crossing.value,
            pedestrian_count,
        )
        self._emit("pedestrian_request", request.model_dump(mode="json"))
        return request

    def _pending_pedestrian_requests(self) -> list[PedestrianRequest]:
        return [request for request in self._pedestrian_requests.values() if not request.is_served]

    def _longest_pedestrian_wait(self) -> float:
        pending = self._pending_pedestrian_requests()
        return max((request.waiting_seconds for request in pending), default=0.0)

    def _pedestrian_phase_duration(self) -> int:
        """Walk time, extended when an accessibility request is waiting."""
        pending = self._pending_pedestrian_requests()
        duration = settings.pedestrian_crossing_duration
        if any(request.accessibility_extension for request in pending):
            duration = int(duration * 1.5)
        return duration

    def _complete_pedestrian_phase(self) -> None:
        """Mark every waiting request as served and record how long it waited."""
        served_at = utc_now()
        for request in self._pending_pedestrian_requests():
            request.served_at = served_at
            metrics.record_pedestrian_wait(request.waiting_seconds)

        self.performance_metrics["pedestrian_phases_served"] += 1
        self.status.pending_pedestrian_requests = 0
        self._emit(
            "pedestrian_served", {"intersection_id": self.intersection_id, "served_at": served_at.isoformat()}
        )

    @property
    def pending_pedestrian_requests(self) -> list[PedestrianRequest]:
        return self._pending_pedestrian_requests()

    # --- configuration -------------------------------------------------------
    async def apply_plan_update(self, update: SignalPlanUpdate) -> dict[str, Any]:
        """Retune the controller at runtime. Returns the fields actually applied."""
        applied: dict[str, Any] = {}

        async with self._lock:
            if update.adaptive_mode is not None:
                self.status.adaptive_mode = update.adaptive_mode
                applied["adaptive_mode"] = update.adaptive_mode

            for field_name in (
                "minimum_green_duration",
                "maximum_green_duration",
                "default_green_signal_duration",
                "yellow_signal_duration",
                "seconds_per_queued_vehicle",
            ):
                value = getattr(update, field_name)
                if value is not None:
                    setattr(settings, field_name, value)
                    applied[field_name] = value

        if settings.minimum_green_duration > settings.maximum_green_duration:
            raise ValueError("minimum_green_duration cannot exceed maximum_green_duration")

        self.logger.info("Signal plan updated at %s: %s", self.intersection_id, applied)
        return applied

    # --- reporting -----------------------------------------------------------
    async def get_current_status(self) -> IntersectionStatus:
        """Current intersection state."""
        self.status.pending_pedestrian_requests = len(self._pending_pedestrian_requests())
        self.status.system_status = "operational" if self._running else "stopped"
        return self.status

    def get_performance_metrics(self) -> dict[str, Any]:
        return dict(self.performance_metrics)

    def _emit(self, event_type: str, payload: Any) -> None:
        """Publish an event, never letting a subscriber break the control loop."""
        if self._on_event is None:
            return
        try:
            self._on_event(event_type, payload)
        except Exception as error:  # pragma: no cover - defensive
            self.log_error_with_context(error, "emit_event")
