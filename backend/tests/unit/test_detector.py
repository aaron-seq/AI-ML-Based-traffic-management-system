"""Detection pipeline tests.

The model itself is mocked: these tests cover our logic — lane assignment,
aggregation, capacity weighting and error handling — not YOLO's accuracy.
"""

from __future__ import annotations

import pytest

from app.models.traffic_models import APPROACH_DIRECTIONS, LaneDirection, VehicleType
from app.services.intelligent_vehicle_detector import (
    COCO_CLASS_MAP,
    DetectorNotReadyError,
    IntelligentVehicleDetector,
    UnreadableMediaError,
    assign_lane,
)


class TestLaneAssignment:
    """The old implementation used four narrow bands covering ~20% of the frame
    and dropped everything else as ``unknown``, so most detections never
    reached the signal controller. Sector assignment must cover the whole
    frame."""

    @pytest.mark.parametrize(
        ("x", "y", "expected"),
        [
            (0.5, 0.1, LaneDirection.NORTH),
            (0.5, 0.9, LaneDirection.SOUTH),
            (0.9, 0.5, LaneDirection.EAST),
            (0.1, 0.5, LaneDirection.WEST),
            # Corners resolve by whichever axis dominates.
            (0.1, 0.05, LaneDirection.NORTH),
            (0.95, 0.6, LaneDirection.EAST),
        ],
    )
    def test_assigns_the_expected_approach(self, x, y, expected):
        assert assign_lane(x, y) == expected

    def test_every_point_in_the_frame_gets_an_approach(self):
        unassigned = [
            (x / 20, y / 20)
            for x in range(21)
            for y in range(21)
            if assign_lane(x / 20, y / 20) == LaneDirection.UNKNOWN
        ]

        # Only the exact centre is genuinely ambiguous.
        assert unassigned == [(0.5, 0.5)]

    def test_the_exact_centre_is_reported_as_unknown(self):
        assert assign_lane(0.5, 0.5) == LaneDirection.UNKNOWN

    def test_diagonal_ties_prefer_the_vertical_axis(self):
        # |dx| == |dy|: the implementation documents north/south winning.
        assert assign_lane(0.75, 0.25) == LaneDirection.NORTH
        assert assign_lane(0.25, 0.75) == LaneDirection.SOUTH


class TestResultExtraction:
    def test_maps_coco_classes_onto_our_taxonomy(self, blank_frame, fake_detection_boxes):
        detector = IntelligentVehicleDetector()
        vehicles = detector._extract_vehicles(fake_detection_boxes, blank_frame.shape)

        types = [vehicle.vehicle_type for vehicle in vehicles]
        assert VehicleType.CAR in types
        assert VehicleType.BUS in types
        assert VehicleType.TRUCK in types
        assert VehicleType.PEDESTRIAN in types

    def test_ignores_classes_outside_the_map(self, blank_frame):
        from tests.conftest import FakeBox, FakeResult

        # 63 is "couch" in COCO: present in street scenes, irrelevant to traffic.
        results = [FakeResult([FakeBox(63, 0.9, (10, 10, 60, 60))])]
        detector = IntelligentVehicleDetector()

        assert detector._extract_vehicles(results, blank_frame.shape) == []

    def test_drops_degenerate_boxes_instead_of_failing_the_frame(self, blank_frame):
        from tests.conftest import FakeBox, FakeResult

        results = [
            FakeResult(
                [
                    FakeBox(2, 0.9, (100, 100, 100, 100)),  # zero area
                    FakeBox(2, 0.9, (480, 100, 520, 180)),  # valid
                ]
            )
        ]
        vehicles = IntelligentVehicleDetector()._extract_vehicles(results, blank_frame.shape)

        assert len(vehicles) == 1

    def test_handles_a_frame_with_no_detections(self, blank_frame):
        from tests.conftest import FakeResult

        detector = IntelligentVehicleDetector()
        assert detector._extract_vehicles([FakeResult([])], blank_frame.shape) == []
        assert detector._extract_vehicles([], blank_frame.shape) == []

    def test_captures_track_ids_when_tracking_is_active(self, blank_frame):
        from tests.conftest import FakeBox, FakeResult

        results = [FakeResult([FakeBox(2, 0.9, (480, 100, 520, 180), track_id=42)])]
        vehicles = IntelligentVehicleDetector()._extract_vehicles(results, blank_frame.shape)

        assert vehicles[0].track_id == 42

    def test_centres_are_normalised_into_the_unit_square(self, blank_frame, fake_detection_boxes):
        vehicles = IntelligentVehicleDetector()._extract_vehicles(fake_detection_boxes, blank_frame.shape)

        for vehicle in vehicles:
            assert 0.0 <= vehicle.center.x <= 1.0
            assert 0.0 <= vehicle.center.y <= 1.0


class TestAggregation:
    def test_counts_vehicles_per_approach_and_excludes_pedestrians(self, blank_frame, fake_detection_boxes):
        detector = IntelligentVehicleDetector()
        vehicles = detector._extract_vehicles(fake_detection_boxes, blank_frame.shape)
        counts = detector._count_by_lane(vehicles)

        assert counts[LaneDirection.NORTH] == 1  # the pedestrian is not counted
        assert counts[LaneDirection.SOUTH] == 1
        assert counts[LaneDirection.EAST] == 1
        assert counts[LaneDirection.WEST] == 1

    def test_reports_every_approach_even_when_empty(self, blank_frame):
        counts = IntelligentVehicleDetector()._count_by_lane([])
        assert set(counts) == set(APPROACH_DIRECTIONS)
        assert all(value == 0 for value in counts.values())

    def test_weights_large_vehicles_more_heavily(self, blank_frame, fake_detection_boxes):
        detector = IntelligentVehicleDetector()
        vehicles = detector._extract_vehicles(fake_detection_boxes, blank_frame.shape)
        stats = detector._build_lane_statistics(vehicles)

        # A bus occupies far more road space than a car.
        assert stats[LaneDirection.EAST].passenger_car_units == pytest.approx(2.5)
        assert stats[LaneDirection.NORTH].passenger_car_units == pytest.approx(1.0)

    def test_counts_waiting_pedestrians_separately(self, blank_frame, fake_detection_boxes):
        detector = IntelligentVehicleDetector()
        vehicles = detector._extract_vehicles(fake_detection_boxes, blank_frame.shape)
        stats = detector._build_lane_statistics(vehicles)

        assert stats[LaneDirection.NORTH].pedestrians_waiting == 1

    def test_builds_a_complete_result(self, blank_frame, fake_detection_boxes):
        detector = IntelligentVehicleDetector()
        vehicles = detector._extract_vehicles(fake_detection_boxes, blank_frame.shape)
        result = detector._build_result(vehicles, processing_time=0.05, source="image")

        assert result.total_vehicles == 4
        assert result.pedestrian_count == 1
        assert result.busiest_lane in APPROACH_DIRECTIONS
        assert result.total_passenger_car_units == pytest.approx(6.5)

    def test_zero_processing_time_is_valid(self, blank_frame):
        """Cached or trivially fast results must not fail validation; the old
        schema required ``processing_time > 0``."""
        result = IntelligentVehicleDetector()._build_result([], processing_time=0.0, source="image")
        assert result.processing_time == 0.0


class TestReadiness:
    async def test_refuses_inference_before_the_model_is_loaded(self, blank_frame):
        detector = IntelligentVehicleDetector()
        assert detector.is_ready() is False

        with pytest.raises(DetectorNotReadyError):
            await detector.analyze_frame(blank_frame)

    async def test_reports_an_unreadable_image_clearly(self, tmp_path):
        detector = IntelligentVehicleDetector()
        detector._ready = True
        detector._model = object()

        corrupt = tmp_path / "broken.jpg"
        corrupt.write_bytes(b"this is not a jpeg")

        with pytest.raises(UnreadableMediaError, match="Could not decode"):
            await detector.analyze_intersection_image(str(corrupt))

    async def test_cleanup_releases_the_model(self):
        detector = IntelligentVehicleDetector()
        detector._ready = True
        detector._model = object()

        await detector.cleanup()
        assert detector.is_ready() is False


class TestVehicleTaxonomy:
    def test_pedestrians_do_not_occupy_a_vehicle_queue(self):
        assert VehicleType.PEDESTRIAN.is_vehicle is False
        assert VehicleType.CAR.is_vehicle is True

    def test_capacity_weights_are_ordered_sensibly(self):
        assert (
            VehicleType.BICYCLE.passenger_car_equivalent
            < VehicleType.MOTORCYCLE.passenger_car_equivalent
            < VehicleType.CAR.passenger_car_equivalent
            < VehicleType.TRUCK.passenger_car_equivalent
            < VehicleType.BUS.passenger_car_equivalent
        )

    def test_the_class_map_covers_every_road_user_we_care_about(self):
        mapped = set(COCO_CLASS_MAP.values())
        assert {VehicleType.CAR, VehicleType.BUS, VehicleType.TRUCK, VehicleType.PEDESTRIAN} <= mapped
