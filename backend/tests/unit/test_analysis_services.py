"""Tests for forecasting, impact modelling, analytics and corridor coordination."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config import settings
from app.models.traffic_models import (
    CongestionLevel,
    IntersectionDefinition,
    LaneDirection,
    VehicleDetectionResult,
    utc_now,
)
from app.services.impact_service import uniform_delay_seconds
from app.services.network_coordinator import IntersectionNotFoundError


# --------------------------------------------------------------------------- #
# Forecasting
# --------------------------------------------------------------------------- #
class TestForecasting:
    def feed(self, service, count: int, vehicles: int = 10, intersection: str = "main") -> None:
        """Record ``count`` minute-spaced observations across every approach."""
        base = utc_now() - timedelta(minutes=count)
        for index in range(count):
            service.record_observation(
                intersection,
                {
                    LaneDirection.NORTH: vehicles,
                    LaneDirection.SOUTH: 2,
                    LaneDirection.EAST: 1,
                    LaneDirection.WEST: 1,
                },
                base + timedelta(minutes=index),
            )

    def test_says_what_it_needs_when_history_is_thin(self, forecast_service):
        self.feed(forecast_service, 2)
        result = forecast_service.forecast("main")

        assert result.points == []
        assert result.confidence == 0.0
        assert "at least" in (result.notes or "")

    def test_produces_a_point_per_requested_horizon(self, forecast_service):
        self.feed(forecast_service, 30)
        result = forecast_service.forecast("main", horizons_minutes=(5, 15, 30))

        assert [point.horizon_minutes for point in result.points] == [5, 15, 30]

    def test_prediction_bounds_bracket_the_expectation(self, forecast_service):
        self.feed(forecast_service, 30)
        result = forecast_service.forecast("main")

        for point in result.points:
            assert point.lower_bound <= point.expected_vehicles <= point.upper_bound

    def test_uncertainty_widens_with_the_horizon(self, forecast_service):
        # Vary the demand so the series has non-zero spread.
        for index in range(40):
            forecast_service.record_observation(
                "main",
                {LaneDirection.NORTH: 5 + (index % 7)},
                utc_now() - timedelta(minutes=40 - index),
            )

        result = forecast_service.forecast("main", horizons_minutes=(5, 60))
        near, far = result.points

        assert (far.upper_bound - far.lower_bound) > (near.upper_bound - near.lower_bound)

    def test_never_predicts_negative_demand(self, forecast_service):
        for index in range(30):
            forecast_service.record_observation("main", {LaneDirection.NORTH: 0 if index % 2 else 1})

        result = forecast_service.forecast("main")
        assert all(point.lower_bound >= 0 for point in result.points)

    def test_confidence_rises_with_more_history(self, forecast_service):
        self.feed(forecast_service, 10, intersection="thin")
        self.feed(forecast_service, 200, intersection="rich")

        thin = forecast_service.forecast("thin").confidence
        rich = forecast_service.forecast("rich").confidence

        assert rich > thin

    def test_tracks_each_approach_independently(self, forecast_service):
        self.feed(forecast_service, 20)
        per_lane = forecast_service.forecast_all_lanes("main")

        assert set(per_lane) == {"north", "south", "east", "west"}
        assert per_lane["north"].points[0].expected_vehicles > per_lane["east"].points[0].expected_vehicles

    def test_unknown_intersection_yields_an_empty_forecast_not_an_error(self, forecast_service):
        result = forecast_service.forecast("never_seen")
        assert result.observations_used == 0
        assert result.points == []


# --------------------------------------------------------------------------- #
# Impact modelling
# --------------------------------------------------------------------------- #
class TestUniformDelay:
    def test_more_green_means_less_delay(self):
        high = uniform_delay_seconds(cycle_seconds=120, green_seconds=30, arrival_rate_per_second=0.1)
        low = uniform_delay_seconds(cycle_seconds=120, green_seconds=90, arrival_rate_per_second=0.1)
        assert low < high

    def test_no_green_means_waiting_a_full_cycle(self):
        assert uniform_delay_seconds(120, 0, 0.1) == 120

    def test_a_degenerate_cycle_produces_no_delay(self):
        assert uniform_delay_seconds(0, 0, 0.1) == 0.0

    def test_delay_is_never_negative(self):
        for green in range(0, 121, 10):
            assert uniform_delay_seconds(120, green, 0.2) >= 0


class TestImpactService:
    async def test_adaptive_control_beats_a_fixed_time_baseline_under_load(
        self, impact_service, controller, lane_statistics
    ):
        await controller.update_vehicle_counts(
            {lane: stats.vehicle_count for lane, stats in lane_statistics.items()},
            lane_statistics,
        )
        impact_service.record_cycle(controller.intersection_id, vehicles_served=40)

        estimate = impact_service.estimate(await controller.get_current_status())

        assert estimate.delay_saved_seconds > 0
        assert estimate.delay_reduction_percent > 0

    async def test_savings_are_internally_consistent(self, impact_service, controller):
        impact_service.record_cycle(controller.intersection_id, vehicles_served=100)
        estimate = impact_service.estimate(await controller.get_current_status())

        expected_fuel = estimate.idling_hours_avoided * settings.idle_fuel_litres_per_hour
        assert estimate.fuel_litres_saved == pytest.approx(expected_fuel, rel=1e-2)

        expected_co2 = estimate.fuel_litres_saved * settings.co2_kg_per_litre_petrol
        assert estimate.co2_kg_avoided == pytest.approx(expected_co2, rel=1e-2)

    async def test_every_estimate_carries_its_assumptions(self, impact_service, controller):
        estimate = impact_service.estimate(await controller.get_current_status())

        assert "method" in estimate.assumptions
        assert "caveat" in estimate.assumptions
        # The caveat must make clear these are not measurements.
        assert "estimate" in str(estimate.assumptions["caveat"]).lower()

    async def test_cumulative_totals_accumulate(self, impact_service, controller):
        status = await controller.get_current_status()
        impact_service.record_cycle(controller.intersection_id, vehicles_served=50)

        impact_service.estimate(status)
        first = impact_service.cumulative_totals(controller.intersection_id)["co2_kg_avoided"]

        impact_service.estimate(status)
        second = impact_service.cumulative_totals(controller.intersection_id)["co2_kg_avoided"]

        assert second >= first

    def test_projection_refuses_to_extrapolate_from_nothing(self, impact_service):
        projection = impact_service.annualised_projection("main", observed_hours=0)
        assert projection["available"] is False

    def test_short_observations_are_flagged_as_low_confidence(self, impact_service):
        projection = impact_service.annualised_projection("main", observed_hours=2)
        assert projection["confidence"] == "low"
        assert "caveat" in projection

    def test_a_full_week_upgrades_confidence(self, impact_service):
        projection = impact_service.annualised_projection("main", observed_hours=200)
        assert projection["confidence"] == "moderate"


# --------------------------------------------------------------------------- #
# Corridor coordination
# --------------------------------------------------------------------------- #
class TestNetworkCoordination:
    async def test_registers_a_default_intersection(self, network):
        assert network.exists("main_intersection")
        assert network.count == 1

    async def test_rejects_a_duplicate_identifier(self, network):
        with pytest.raises(ValueError, match="already exists"):
            await network.add_intersection(
                IntersectionDefinition(intersection_id="main_intersection", name="Duplicate")
            )

    async def test_unknown_identifiers_raise_a_typed_error(self, network):
        with pytest.raises(IntersectionNotFoundError):
            network.get("does_not_exist")

    async def test_green_wave_offsets_follow_distance_over_speed(self, network):
        await network.add_intersection(
            IntersectionDefinition(intersection_id="second", name="Second", distance_from_previous_metres=500)
        )

        offsets = network.green_wave_offsets(design_speed_kph=50)

        assert offsets["main_intersection"] == 0.0
        # 500 m at 50 km/h (13.89 m/s) = 36.0 s
        assert offsets["second"] == pytest.approx(36.0, abs=0.1)

    async def test_offsets_accumulate_along_the_corridor(self, network):
        for index, distance in enumerate([400, 400, 400], start=2):
            await network.add_intersection(
                IntersectionDefinition(
                    intersection_id=f"j{index}",
                    name=f"Junction {index}",
                    distance_from_previous_metres=distance,
                )
            )

        offsets = network.green_wave_offsets(design_speed_kph=36)  # 10 m/s
        assert offsets["j2"] == pytest.approx(40.0, abs=0.1)
        assert offsets["j3"] == pytest.approx(80.0, abs=0.1)
        assert offsets["j4"] == pytest.approx(120.0, abs=0.1)

    async def test_faster_design_speed_shortens_the_offsets(self, network):
        await network.add_intersection(
            IntersectionDefinition(intersection_id="second", name="Second", distance_from_previous_metres=600)
        )

        slow = network.green_wave_offsets(design_speed_kph=30)["second"]
        fast = network.green_wave_offsets(design_speed_kph=60)["second"]

        assert fast == pytest.approx(slow / 2, rel=1e-3)

    async def test_the_plan_reports_a_shared_cycle_length(self, network):
        plan = await network.coordination_plan()

        # Coordinated signals must share a cycle or the offsets drift apart.
        assert plan["common_cycle_seconds"] > 0
        assert plan["corridor"] == ["main_intersection"]

    async def test_summaries_describe_every_intersection(self, network):
        await network.add_intersection(IntersectionDefinition(intersection_id="second", name="Second"))
        rows = await network.summaries()

        assert {row.intersection_id for row in rows} == {"main_intersection", "second"}
        assert all(isinstance(row.congestion_level, CongestionLevel) for row in rows)

    async def test_removing_an_intersection_stops_its_controller(self, network):
        await network.add_intersection(IntersectionDefinition(intersection_id="temporary", name="Temp"))
        controller = network.get("temporary")

        await network.remove_intersection("temporary")

        assert network.exists("temporary") is False
        assert controller.is_running is False

    async def test_aggregate_metrics_sum_across_the_corridor(self, network):
        await network.add_intersection(IntersectionDefinition(intersection_id="second", name="Second"))
        totals = network.aggregate_metrics()

        assert totals["intersections"] == 2
        assert "cycles_completed" in totals


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #
def build_detection(total: int = 5, north: int = 3) -> VehicleDetectionResult:
    return VehicleDetectionResult(
        detection_id=f"det_{total}_{north}",
        total_vehicles=total,
        lane_counts={
            LaneDirection.NORTH: north,
            LaneDirection.SOUTH: max(total - north, 0),
            LaneDirection.EAST: 0,
            LaneDirection.WEST: 0,
        },
        processing_time=0.12,
        source="image",
    )


class TestAnalytics:
    async def test_records_detections_and_tracks_running_metrics(self, analytics):
        await analytics.record_detection(build_detection(5, 3))
        await analytics.record_detection(build_detection(9, 7))

        metrics = analytics.performance_metrics
        assert metrics["total_detections"] == 2
        assert metrics["total_vehicles_observed"] == 14
        assert metrics["peak_vehicles_observed"] == 9
        assert metrics["busiest_lane"] == "north"

    async def test_summary_works_before_any_data_arrives(self, analytics):
        summary = await analytics.generate_summary("current")

        assert summary["detection_count"] == 0
        assert "recent_traffic" not in summary

    async def test_summary_describes_recent_traffic(self, analytics):
        for _ in range(5):
            await analytics.record_detection(build_detection(6, 4))

        summary = await analytics.generate_summary("current")
        recent = summary["recent_traffic"]

        assert recent["sample_size"] == 5
        assert recent["average_vehicles"] == 6
        assert recent["lane_distribution_percent"]["north"] == pytest.approx(66.7, abs=0.2)

    async def test_detects_a_rising_demand_trend(self, analytics):
        for count in (1, 1, 1, 1, 20, 20, 20, 20):
            await analytics.record_detection(build_detection(count, count))

        summary = await analytics.generate_summary("current")
        assert summary["traffic_flow"]["trend"] == "increasing"

    async def test_hourly_summary_reports_absence_of_data_clearly(self, analytics):
        summary = await analytics.generate_summary("hourly")
        assert "message" in summary

    async def test_history_falls_back_to_memory_when_persistence_is_off(self, analytics):
        await analytics.record_detection(build_detection())
        history = await analytics.get_history(hours=1)

        assert history["source"] == "memory"
        assert history["count"] == 1
        assert "note" in history

    async def test_heatmap_buckets_by_hour(self, analytics):
        await analytics.record_detection(build_detection())
        heatmap = await analytics.get_traffic_heatmap_data(hours=24)

        assert heatmap["peak_hour"] == utc_now().strftime("%H")

    async def test_heatmap_reports_an_empty_window_gracefully(self, analytics):
        result = await analytics.get_traffic_heatmap_data(hours=1)
        assert "message" in result

    async def test_performance_report_includes_percentiles(self, analytics):
        for _ in range(10):
            await analytics.record_detection(build_detection())

        report = await analytics.get_performance_report()
        assert report["pipeline"]["p95_processing_seconds"] > 0
        assert report["data_collection"]["detections_recorded"] == 10

    async def test_history_is_bounded_so_memory_cannot_grow_without_limit(self):
        from app.services.analytics_service import TrafficAnalyticsService

        service = TrafficAnalyticsService(max_history_size=5)
        await service.initialize()
        for index in range(20):
            await service.record_detection(build_detection(index))

        assert len(service._detections) == 5
        await service.cleanup()
