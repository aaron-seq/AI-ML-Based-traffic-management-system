"""Impact modelling: what adaptive control is actually worth.

Traffic projects are funded on outcomes -- time saved, fuel burnt, emissions
avoided -- not on detection accuracy. This service converts the controller's
observed behaviour into those figures so the value of a deployment can be
stated in terms a transport authority or city budget holder can act on.

Everything here is a **model estimate**, not a measurement. Delay comes from a
Webster-style uniform-arrival approximation; fuel and CO2 come from published
average factors that vary widely by fleet mix and climate. Every result carries
its assumptions so the numbers can be audited and re-based on local data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..core import metrics
from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import ImpactEstimate, IntersectionStatus, utc_now
from .adaptive_traffic_manager import SATURATION_FLOW_PER_SECOND


def uniform_delay_seconds(
    cycle_seconds: float, green_seconds: float, arrival_rate_per_second: float
) -> float:
    """Average delay per vehicle for a signalised approach.

    This is the uniform-delay term of Webster's formula:

        d = C(1 - g/C)^2 / (2(1 - min(x, 1) * g/C))

    where ``C`` is cycle length, ``g`` is effective green and ``x`` is the
    degree of saturation. It assumes vehicles arrive at a constant rate, which
    understates delay when arrivals are bunched but is the standard first-order
    estimate and is well suited to comparing two signal plans on equal terms.
    """
    if cycle_seconds <= 0:
        return 0.0

    green_ratio = min(max(green_seconds / cycle_seconds, 0.0), 1.0)
    capacity_per_second = SATURATION_FLOW_PER_SECOND * green_ratio

    if capacity_per_second <= 0:
        # No green at all: everything waits a full cycle.
        return cycle_seconds

    saturation = min(arrival_rate_per_second / capacity_per_second, 0.95)
    denominator = 2 * (1 - saturation * green_ratio)
    if denominator <= 0:
        return cycle_seconds

    return cycle_seconds * (1 - green_ratio) ** 2 / denominator


class TrafficImpactService(LoggerMixin):
    """Estimates delay, fuel, CO2 and economic savings versus a fixed-time plan."""

    def __init__(self) -> None:
        self._window_start: dict[str, datetime] = {}
        self._vehicles_served: dict[str, int] = {}
        self._cumulative: dict[str, dict[str, float]] = {}
        self._ready = False

    async def initialize(self) -> None:
        self._ready = True
        self.logger.info("Impact service initialised")

    def is_ready(self) -> bool:
        return self._ready

    async def cleanup(self) -> None:
        self._window_start.clear()
        self._vehicles_served.clear()
        self._cumulative.clear()
        self._ready = False

    # --- ingestion -----------------------------------------------------------
    def record_cycle(self, intersection_id: str, vehicles_served: int) -> None:
        """Note that a signal cycle discharged ``vehicles_served`` vehicles."""
        self._window_start.setdefault(intersection_id, utc_now())
        self._vehicles_served[intersection_id] = (
            self._vehicles_served.get(intersection_id, 0) + vehicles_served
        )

    # --- estimation ----------------------------------------------------------
    def estimate(
        self,
        status: IntersectionStatus,
        adaptive_cycle_seconds: float | None = None,
        window_hours: float | None = None,
    ) -> ImpactEstimate:
        """Compare the running adaptive plan against a fixed-time baseline.

        The baseline is a fixed ``TRAFFIC_BASELINE_FIXED_CYCLE_SECONDS`` cycle
        splitting green evenly between the two phases -- what an un-upgraded
        junction typically runs.
        """
        intersection_id = status.intersection_id
        now = utc_now()
        window_start = self._window_start.get(intersection_id, now - timedelta(hours=1))

        elapsed_hours = (
            window_hours
            if window_hours is not None
            else max((now - window_start).total_seconds() / 3600.0, 1 / 60.0)
        )

        vehicles_served = self._vehicles_served.get(intersection_id, 0)
        current_demand = sum(status.vehicle_counts.values())

        # Arrival rate: prefer observed throughput, fall back to the standing
        # queue so a freshly started system still produces a sensible figure.
        if vehicles_served > 0:
            arrival_rate = vehicles_served / (elapsed_hours * 3600.0)
        else:
            arrival_rate = current_demand / float(settings.baseline_fixed_cycle_seconds)

        baseline_cycle = float(settings.baseline_fixed_cycle_seconds)
        baseline_green = (
            baseline_cycle - 2 * (settings.yellow_signal_duration + settings.all_red_clearance_duration)
        ) / 2

        adaptive_cycle = adaptive_cycle_seconds or self._infer_adaptive_cycle(status)
        adaptive_green = (
            adaptive_cycle - 2 * (settings.yellow_signal_duration + settings.all_red_clearance_duration)
        ) / 2

        baseline_delay = uniform_delay_seconds(baseline_cycle, baseline_green, arrival_rate)
        adaptive_delay = uniform_delay_seconds(adaptive_cycle, adaptive_green, arrival_rate)
        delay_saved_per_vehicle = baseline_delay - adaptive_delay

        vehicles_in_window = vehicles_served or current_demand
        total_delay_saved = delay_saved_per_vehicle * vehicles_in_window

        idling_hours = total_delay_saved / 3600.0
        fuel_litres = idling_hours * settings.idle_fuel_litres_per_hour
        co2_kg = fuel_litres * settings.co2_kg_per_litre_petrol
        person_hours = idling_hours * settings.average_vehicle_occupancy
        economic_value = person_hours * settings.value_of_time_per_hour

        estimate = ImpactEstimate(
            intersection_id=intersection_id,
            window_start=window_start,
            window_end=now,
            vehicles_served=vehicles_in_window,
            baseline_delay_seconds=round(baseline_delay * vehicles_in_window, 2),
            adaptive_delay_seconds=round(adaptive_delay * vehicles_in_window, 2),
            delay_saved_seconds=round(total_delay_saved, 2),
            idling_hours_avoided=round(idling_hours, 4),
            fuel_litres_saved=round(fuel_litres, 3),
            co2_kg_avoided=round(co2_kg, 3),
            person_hours_saved=round(person_hours, 4),
            economic_value_saved=round(economic_value, 2),
            currency=settings.impact_currency,
            assumptions={
                "method": "Webster uniform delay, adaptive plan vs fixed-time baseline",
                "baseline_cycle_seconds": baseline_cycle,
                "adaptive_cycle_seconds": round(adaptive_cycle, 1),
                "arrival_rate_vehicles_per_second": round(arrival_rate, 4),
                "saturation_flow_vehicles_per_second_of_green": SATURATION_FLOW_PER_SECOND,
                "idle_fuel_litres_per_hour": settings.idle_fuel_litres_per_hour,
                "co2_kg_per_litre": settings.co2_kg_per_litre_petrol,
                "average_vehicle_occupancy": settings.average_vehicle_occupancy,
                "value_of_time_per_hour": settings.value_of_time_per_hour,
                "caveat": "Modelled estimate, not a measurement. Re-base the factors on local fleet and fuel data before reporting externally.",
            },
        )

        self._accumulate(intersection_id, estimate)
        metrics.record_impact(intersection_id, estimate.co2_kg_avoided, estimate.delay_saved_seconds)
        return estimate

    def _infer_adaptive_cycle(self, status: IntersectionStatus) -> float:
        """Reconstruct the cycle length the adaptive controller is running."""
        queue = sum(stat.passenger_car_units for stat in status.lane_statistics.values())
        green_per_phase = max(
            settings.minimum_green_duration,
            min(
                settings.minimum_green_duration + (queue / 2) * settings.seconds_per_queued_vehicle,
                settings.maximum_green_duration,
            ),
        )
        clearance = settings.yellow_signal_duration + settings.all_red_clearance_duration
        return 2 * (green_per_phase + clearance)

    def _accumulate(self, intersection_id: str, estimate: ImpactEstimate) -> None:
        """Keep a running total so a deployment can report lifetime savings."""
        totals = self._cumulative.setdefault(
            intersection_id,
            {
                "delay_saved_seconds": 0.0,
                "fuel_litres_saved": 0.0,
                "co2_kg_avoided": 0.0,
                "economic_value_saved": 0.0,
            },
        )
        totals["delay_saved_seconds"] += max(0.0, estimate.delay_saved_seconds)
        totals["fuel_litres_saved"] += max(0.0, estimate.fuel_litres_saved)
        totals["co2_kg_avoided"] += max(0.0, estimate.co2_kg_avoided)
        totals["economic_value_saved"] += max(0.0, estimate.economic_value_saved)

    def cumulative_totals(self, intersection_id: str) -> dict[str, float]:
        """Lifetime modelled savings for one intersection."""
        totals = self._cumulative.get(
            intersection_id,
            {
                "delay_saved_seconds": 0.0,
                "fuel_litres_saved": 0.0,
                "co2_kg_avoided": 0.0,
                "economic_value_saved": 0.0,
            },
        )
        return {key: round(value, 3) for key, value in totals.items()}

    def annualised_projection(self, intersection_id: str, observed_hours: float) -> dict[str, Any]:
        """Extrapolate observed savings to a full year.

        Naive linear extrapolation: it assumes the observation window is
        representative, which a single rush hour is not. Treat it as an order of
        magnitude, and observe for at least a full week before quoting it.
        """
        totals = self.cumulative_totals(intersection_id)
        if observed_hours <= 0:
            return {"available": False, "reason": "No observation time recorded yet."}

        scale = 8760.0 / observed_hours
        return {
            "available": True,
            "observed_hours": round(observed_hours, 2),
            "confidence": "low" if observed_hours < 168 else "moderate",
            "annual_delay_saved_hours": round(totals["delay_saved_seconds"] * scale / 3600.0, 1),
            "annual_fuel_litres_saved": round(totals["fuel_litres_saved"] * scale, 1),
            "annual_co2_tonnes_avoided": round(totals["co2_kg_avoided"] * scale / 1000.0, 3),
            "annual_economic_value_saved": round(totals["economic_value_saved"] * scale, 2),
            "currency": settings.impact_currency,
            "caveat": (
                "Linear extrapolation from a short window. Observe at least one full week, "
                "ideally a month, before using these figures in a business case."
            ),
        }
