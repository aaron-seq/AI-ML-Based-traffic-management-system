"""Schema tests: validation rules, computed fields and JSON serialisation."""

from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from app.models.traffic_models import (
    APPROACH_DIRECTIONS,
    BoundingBox,
    CongestionLevel,
    DetectedVehicle,
    EmergencyAlert,
    EmergencyType,
    IntersectionStatus,
    LaneDirection,
    LaneStatistics,
    NormalisedPoint,
    PedestrianRequest,
    SignalPhase,
    TrafficSignal,
    TrafficSignalState,
    VehicleDetectionResult,
    VehicleType,
    utc_now,
)


class TestTimestamps:
    def test_utc_now_is_timezone_aware(self):
        """Naive timestamps from the deprecated ``datetime.utcnow()`` compared
        incorrectly against aware ones and could not be serialised reliably."""
        moment = utc_now()

        assert moment.tzinfo is not None
        assert moment.utcoffset() == UTC.utcoffset(None)

    def test_models_default_to_aware_timestamps(self):
        signal = TrafficSignal(
            signal_id="s",
            direction=LaneDirection.NORTH,
            current_state=TrafficSignalState.RED,
            remaining_time=10,
        )
        assert signal.last_updated.tzinfo is not None


class TestBoundingBox:
    def test_accepts_a_well_formed_box(self):
        box = BoundingBox(x1=10, y1=20, x2=110, y2=140)
        assert box.area == 100 * 120

    @pytest.mark.parametrize(
        "coordinates",
        [
            {"x1": 100, "y1": 10, "x2": 50, "y2": 60},  # x2 before x1
            {"x1": 10, "y1": 100, "x2": 60, "y2": 50},  # y2 before y1
            {"x1": 10, "y1": 10, "x2": 10, "y2": 60},  # zero width
        ],
    )
    def test_rejects_an_inverted_or_degenerate_box(self, coordinates):
        with pytest.raises(ValidationError):
            BoundingBox(**coordinates)

    def test_rejects_negative_coordinates(self):
        with pytest.raises(ValidationError):
            BoundingBox(x1=-5, y1=0, x2=10, y2=10)


class TestNormalisedPoint:
    def test_accepts_the_unit_square(self):
        assert NormalisedPoint(x=0.0, y=1.0).x == 0.0

    @pytest.mark.parametrize(("x", "y"), [(-0.1, 0.5), (0.5, 1.2)])
    def test_rejects_points_outside_the_frame(self, x, y):
        with pytest.raises(ValidationError):
            NormalisedPoint(x=x, y=y)


class TestDetectedVehicle:
    def build(self, **overrides) -> DetectedVehicle:
        payload = {
            "vehicle_type": VehicleType.CAR,
            "confidence": 0.9,
            "bounding_box": BoundingBox(x1=0, y1=0, x2=50, y2=50),
            "center": NormalisedPoint(x=0.5, y=0.2),
            "lane": LaneDirection.NORTH,
        }
        payload.update(overrides)
        return DetectedVehicle(**payload)

    def test_confidence_must_be_a_probability(self):
        with pytest.raises(ValidationError):
            self.build(confidence=1.4)

    def test_exposes_its_capacity_weight(self):
        assert self.build(vehicle_type=VehicleType.BUS).passenger_car_units == 2.5

    def test_speed_is_optional(self):
        assert self.build().speed_kph is None
        assert self.build(speed_kph=42.5).speed_kph == 42.5


class TestVehicleDetectionResult:
    def test_fills_in_every_approach(self):
        result = VehicleDetectionResult(
            detection_id="d1",
            total_vehicles=2,
            lane_counts={LaneDirection.NORTH: 2},
            processing_time=0.1,
        )

        for lane in APPROACH_DIRECTIONS:
            assert lane in result.lane_counts

    def test_identifies_the_busiest_approach(self):
        result = VehicleDetectionResult(
            detection_id="d1",
            total_vehicles=9,
            lane_counts={LaneDirection.NORTH: 2, LaneDirection.EAST: 7},
            processing_time=0.1,
        )
        assert result.busiest_lane == LaneDirection.EAST

    def test_reports_no_busiest_approach_when_empty(self):
        result = VehicleDetectionResult(detection_id="d", total_vehicles=0, processing_time=0.1)
        assert result.busiest_lane is None

    def test_zero_processing_time_is_allowed(self):
        assert (
            VehicleDetectionResult(detection_id="d", total_vehicles=0, processing_time=0.0).processing_time
            == 0.0
        )

    def test_negative_totals_are_rejected(self):
        with pytest.raises(ValidationError):
            VehicleDetectionResult(detection_id="d", total_vehicles=-1, processing_time=0.1)

    def test_serialises_cleanly_to_json(self):
        """WebSocket frames are JSON; a raw datetime in the payload used to
        break ``send_json``."""
        result = VehicleDetectionResult(detection_id="d", total_vehicles=0, processing_time=0.1)
        payload = result.model_dump(mode="json")

        assert isinstance(payload["detection_timestamp"], str)
        assert isinstance(payload["lane_counts"], dict)


class TestCongestionBanding:
    @pytest.mark.parametrize(
        ("units", "expected"),
        [
            (0, CongestionLevel.FREE_FLOW),
            (2, CongestionLevel.FREE_FLOW),
            (5, CongestionLevel.LIGHT),
            (10, CongestionLevel.MODERATE),
            (18, CongestionLevel.HEAVY),
            (40, CongestionLevel.CONGESTED),
        ],
    )
    def test_bands_are_monotonic(self, units, expected):
        assert CongestionLevel.from_queue(units) == expected


class TestEmergencyAlert:
    def build(self, **overrides) -> EmergencyAlert:
        payload = {
            "alert_id": "a1",
            "emergency_type": EmergencyType.AMBULANCE,
            "detected_lane": LaneDirection.NORTH,
        }
        payload.update(overrides)
        return EmergencyAlert(**payload)

    def test_reports_elapsed_time(self):
        """The controller called ``get_time_since_alert()``, which never existed
        on the model and raised AttributeError on every expiry check."""
        alert = self.build()
        assert alert.seconds_since_alert() >= 0

    def test_a_fresh_alert_has_not_expired(self):
        assert self.build(override_duration=600).has_expired() is False

    def test_an_old_alert_has_expired(self):
        alert = self.build(override_duration=1)
        object.__setattr__(alert, "created_at", alert.created_at.replace(year=2020))
        assert alert.has_expired() is True

    def test_priority_is_bounded(self):
        with pytest.raises(ValidationError):
            self.build(priority_level=9)

    def test_override_duration_must_be_positive(self):
        with pytest.raises(ValidationError):
            self.build(override_duration=0)


class TestPedestrianRequest:
    def test_waiting_time_accrues_until_served(self):
        request = PedestrianRequest(request_id="p1", crossing=LaneDirection.NORTH)

        assert request.is_served is False
        assert request.waiting_seconds >= 0

    def test_serving_freezes_the_waiting_time(self):
        request = PedestrianRequest(request_id="p1", crossing=LaneDirection.NORTH)
        request.served_at = utc_now()

        assert request.is_served is True
        first = request.waiting_seconds
        assert request.waiting_seconds == first

    def test_at_least_one_pedestrian_is_required(self):
        with pytest.raises(ValidationError):
            PedestrianRequest(request_id="p", crossing=LaneDirection.NORTH, pedestrian_count=0)


class TestIntersectionStatus:
    def test_reports_which_approaches_hold_green(self):
        status = IntersectionStatus(
            traffic_signals={
                LaneDirection.NORTH: TrafficSignal(
                    signal_id="n",
                    direction=LaneDirection.NORTH,
                    current_state=TrafficSignalState.GREEN,
                    remaining_time=10,
                ),
                LaneDirection.EAST: TrafficSignal(
                    signal_id="e",
                    direction=LaneDirection.EAST,
                    current_state=TrafficSignalState.RED,
                    remaining_time=10,
                ),
            }
        )

        assert status.green_direction == [LaneDirection.NORTH]

    def test_congestion_reflects_the_total_queue(self):
        status = IntersectionStatus(
            lane_statistics={
                LaneDirection.NORTH: LaneStatistics(
                    lane=LaneDirection.NORTH, vehicle_count=20, passenger_car_units=25.0
                )
            }
        )
        assert status.congestion_level == CongestionLevel.CONGESTED

    def test_defaults_to_all_red(self):
        assert IntersectionStatus().current_phase == SignalPhase.ALL_RED

    def test_serialises_to_json_for_the_websocket(self):
        payload = IntersectionStatus().model_dump(mode="json")

        assert isinstance(payload["last_updated"], str)
        assert payload["current_phase"] == "all_red"


class TestLaneDirection:
    def test_knows_its_axis(self):
        assert LaneDirection.NORTH.is_north_south is True
        assert LaneDirection.EAST.is_north_south is False

    def test_knows_its_opposite(self):
        assert LaneDirection.NORTH.opposite == LaneDirection.SOUTH
        assert LaneDirection.WEST.opposite == LaneDirection.EAST

    def test_the_approach_tuple_excludes_the_unknown_sentinel(self):
        assert LaneDirection.UNKNOWN not in APPROACH_DIRECTIONS
        assert len(APPROACH_DIRECTIONS) == 4
