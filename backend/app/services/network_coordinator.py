"""Corridor-level coordination across several intersections.

A single adaptive intersection helps locally but can push its problem to the
next junction. This registry owns every controller in the deployment and, when
green-wave coordination is enabled, computes the phase offsets that let a
platoon of vehicles travel the corridor without stopping.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Any

from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import (
    IntersectionDefinition,
    IntersectionSummary,
    LaneDirection,
    LaneStatistics,
)
from .adaptive_traffic_manager import AdaptiveTrafficManager

#: Identifier used when the caller does not specify an intersection.
DEFAULT_INTERSECTION_ID = "main_intersection"


class IntersectionNotFoundError(KeyError):
    """Raised when an unknown intersection id is requested."""

    def __init__(self, intersection_id: str) -> None:
        super().__init__(intersection_id)
        self.intersection_id = intersection_id

    def __str__(self) -> str:
        return f"Unknown intersection: {self.intersection_id}"


class TrafficNetwork(LoggerMixin):
    """Owns the controllers for every intersection in the deployment."""

    def __init__(self, on_event: Callable[[str, Any], None] | None = None) -> None:
        self._controllers: dict[str, AdaptiveTrafficManager] = {}
        self._definitions: dict[str, IntersectionDefinition] = {}
        #: Corridor order, used to compute green-wave offsets.
        self._corridor: list[str] = []
        self._on_event = on_event
        self._lock = asyncio.Lock()

    # --- lifecycle -----------------------------------------------------------
    async def initialize(self) -> None:
        """Create the default intersection so the API works out of the box."""
        await self.add_intersection(
            IntersectionDefinition(intersection_id=DEFAULT_INTERSECTION_ID, name="Main Intersection")
        )

    async def start_all(self) -> None:
        for controller in self._controllers.values():
            await controller.start_simulation()

    async def stop_all(self) -> None:
        for controller in self._controllers.values():
            await controller.stop_simulation()

    async def cleanup(self) -> None:
        for controller in self._controllers.values():
            await controller.cleanup()
        self._controllers.clear()
        self._definitions.clear()
        self._corridor.clear()

    def is_ready(self) -> bool:
        return bool(self._controllers) and all(c.is_ready() for c in self._controllers.values())

    # --- registry ------------------------------------------------------------
    async def add_intersection(self, definition: IntersectionDefinition) -> AdaptiveTrafficManager:
        """Register an intersection, starting its controller if others are running."""
        async with self._lock:
            if definition.intersection_id in self._controllers:
                raise ValueError(f"Intersection {definition.intersection_id} already exists")

            controller = AdaptiveTrafficManager(
                intersection_id=definition.intersection_id,
                name=definition.name,
                on_event=self._on_event,
            )
            self._controllers[definition.intersection_id] = controller
            self._definitions[definition.intersection_id] = definition
            self._corridor.append(definition.intersection_id)

        await controller.initialize()
        self.logger.info("Registered intersection %s (%s)", definition.intersection_id, definition.name)
        return controller

    async def remove_intersection(self, intersection_id: str) -> None:
        """Deregister an intersection and stop its controller."""
        controller = self.get(intersection_id)
        await controller.cleanup()

        async with self._lock:
            self._controllers.pop(intersection_id, None)
            self._definitions.pop(intersection_id, None)
            if intersection_id in self._corridor:
                self._corridor.remove(intersection_id)

        self.logger.info("Removed intersection %s", intersection_id)

    def get(self, intersection_id: str | None = None) -> AdaptiveTrafficManager:
        """Look up a controller, defaulting to the main intersection."""
        key = intersection_id or DEFAULT_INTERSECTION_ID
        controller = self._controllers.get(key)
        if controller is None:
            raise IntersectionNotFoundError(key)
        return controller

    def exists(self, intersection_id: str) -> bool:
        return intersection_id in self._controllers

    @property
    def controllers(self) -> Iterable[AdaptiveTrafficManager]:
        return self._controllers.values()

    @property
    def count(self) -> int:
        return len(self._controllers)

    def definition(self, intersection_id: str) -> IntersectionDefinition:
        definition = self._definitions.get(intersection_id)
        if definition is None:
            raise IntersectionNotFoundError(intersection_id)
        return definition

    async def summaries(self) -> list[IntersectionSummary]:
        """One row per intersection, for corridor overview screens."""
        rows: list[IntersectionSummary] = []
        for controller in self._controllers.values():
            status = await controller.get_current_status()
            rows.append(
                IntersectionSummary(
                    intersection_id=status.intersection_id,
                    name=status.name,
                    current_phase=status.current_phase,
                    total_vehicles=status.total_vehicles,
                    congestion_level=status.congestion_level,
                    emergency_mode_active=status.emergency_mode_active,
                    last_updated=status.last_updated,
                )
            )
        return rows

    # --- green wave ----------------------------------------------------------
    def green_wave_offsets(self, design_speed_kph: float | None = None) -> dict[str, float]:
        """Seconds each intersection's green should lag the corridor's first.

        A platoon leaving intersection *i* reaches intersection *i+1* after
        ``distance / speed`` seconds. Starting that intersection's green at the
        same lag means the platoon arrives to a green light instead of braking.
        This is the classic fixed-offset green wave; it assumes travel in the
        corridor's forward direction and uniform platoon speed.
        """
        speed_kph = design_speed_kph or settings.green_wave_design_speed_kph
        speed_mps = speed_kph / 3.6

        offsets: dict[str, float] = {}
        cumulative = 0.0

        for intersection_id in self._corridor:
            definition = self._definitions.get(intersection_id)
            distance = definition.distance_from_previous_metres if definition else 0.0
            if distance > 0 and speed_mps > 0:
                cumulative += distance / speed_mps
            offsets[intersection_id] = round(cumulative, 1)

        return offsets

    async def coordination_plan(self, design_speed_kph: float | None = None) -> dict[str, Any]:
        """Full corridor plan: offsets, common cycle length and travel time."""
        offsets = self.green_wave_offsets(design_speed_kph)
        speed_kph = design_speed_kph or settings.green_wave_design_speed_kph

        # Coordinated signals must share a common cycle length, otherwise the
        # offsets drift apart within a few cycles. Take the longest demand-driven
        # cycle across the corridor so no intersection is under-served.
        cycle_lengths: list[float] = []
        for controller in self._controllers.values():
            status = await controller.get_current_status()
            queue = sum(stat.passenger_car_units for stat in status.lane_statistics.values())
            cycle_lengths.append(
                2 * (settings.minimum_green_duration + queue * settings.seconds_per_queued_vehicle)
                + 2 * (settings.yellow_signal_duration + settings.all_red_clearance_duration)
            )

        common_cycle = round(max(cycle_lengths)) if cycle_lengths else settings.baseline_fixed_cycle_seconds
        total_distance = sum(
            definition.distance_from_previous_metres for definition in self._definitions.values()
        )

        return {
            "enabled": settings.green_wave_enabled,
            "design_speed_kph": speed_kph,
            "common_cycle_seconds": common_cycle,
            "corridor": list(self._corridor),
            "offsets_seconds": offsets,
            "corridor_length_metres": round(total_distance, 1),
            "corridor_travel_time_seconds": round(total_distance / (speed_kph / 3.6), 1)
            if speed_kph > 0
            else 0.0,
        }

    # --- bulk demand ---------------------------------------------------------
    async def update_counts(
        self,
        intersection_id: str,
        lane_counts: dict[LaneDirection, int],
        lane_statistics: dict[LaneDirection, LaneStatistics] | None = None,
    ) -> None:
        """Push measured queues into one intersection's controller."""
        controller = self.get(intersection_id)
        await controller.update_vehicle_counts(lane_counts, lane_statistics)

    def aggregate_metrics(self) -> dict[str, Any]:
        """Corridor-wide totals across every controller."""
        totals = {
            "intersections": len(self._controllers),
            "cycles_completed": 0,
            "emergency_overrides": 0,
            "pedestrian_phases_served": 0,
            "adaptive_adjustments": 0,
            "total_vehicles_served": 0,
        }
        for controller in self._controllers.values():
            controller_metrics = controller.get_performance_metrics()
            for key in list(totals):
                if key in controller_metrics:
                    totals[key] += controller_metrics[key]
        return totals
