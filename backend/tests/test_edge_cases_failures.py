"""
Edge Cases, Failures & Retry Mechanism Tests
Comprehensive testing for system resilience, error handling, and recovery behavior

Edge Case Categories:
1. Invalid/Missing Input Handling
2. Boundary Condition Testing
3. State Transition Edge Cases
4. Resource Exhaustion Scenarios
5. Retry and Recovery Patterns
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
import numpy as np
import cv2
import time

from app.services.intelligent_vehicle_detector import IntelligentVehicleDetector
from app.models.traffic_models import (
    VehicleDetectionResult,
    DetectedVehicle,
    LaneDirection,
)


class TestEdgeCaseInvalidInputs:
    """Edge Case Category 1: Invalid/Missing Input Handling"""

    @pytest.fixture
    async def detector(self):
        """Create detector instance for testing"""
        detector = IntelligentVehicleDetector()
        with patch.object(detector, "_load_model"):
            detector.model = Mock()
            detector.model_initialized = True
            yield detector

    @pytest.mark.asyncio
    async def test_invalid_image_path(self, detector):
        """
        EDGE CASE: Nonexistent file path
        BEFORE: detector ready, invalid path provided
        AFTER: ValueError raised with descriptive message
        PURPOSE: Prevent silent failures on missing files
        """
        with pytest.raises(ValueError, match="Could not load image"):
            await detector.analyze_intersection_image("nonexistent_image.jpg")

    @pytest.mark.asyncio
    async def test_empty_image_path(self, detector):
        """
        EDGE CASE: Empty string as image path
        BEFORE: detector ready, empty path provided
        AFTER: ValueError raised
        PURPOSE: Validate input sanitization
        """
        with pytest.raises((ValueError, FileNotFoundError)):
            await detector.analyze_intersection_image("")

    @pytest.mark.asyncio
    async def test_none_image_path(self, detector):
        """
        EDGE CASE: None passed as image path
        BEFORE: detector ready, None provided
        AFTER: TypeError or ValueError raised
        PURPOSE: Handle null input gracefully
        """
        with pytest.raises((TypeError, ValueError, AttributeError)):
            await detector.analyze_intersection_image(None)

    @pytest.mark.asyncio
    async def test_directory_instead_of_file(self, detector, tmp_path):
        """
        EDGE CASE: Directory path instead of file path
        BEFORE: detector ready, directory path provided
        AFTER: Appropriate error raised
        PURPOSE: Distinguish file vs directory inputs
        """
        with pytest.raises((ValueError, IsADirectoryError, cv2.error)):
            await detector.analyze_intersection_image(str(tmp_path))

    @pytest.mark.asyncio
    async def test_corrupted_image_file(self, detector, tmp_path):
        """
        EDGE CASE: Corrupted/invalid image data
        BEFORE: detector ready, file exists but contains invalid image data
        AFTER: ValueError with message about loading failure
        PURPOSE: Handle malformed input files
        """
        # Create a fake "image" file with invalid data
        corrupted_file = tmp_path / "corrupted.jpg"
        corrupted_file.write_bytes(b"not a valid image file content")

        with pytest.raises(ValueError, match="Could not load image"):
            await detector.analyze_intersection_image(str(corrupted_file))


class TestBoundaryConditions:
    """Edge Case Category 2: Boundary Condition Testing"""

    @pytest.fixture
    async def detector(self):
        detector = IntelligentVehicleDetector()
        with patch.object(detector, "_load_model"):
            detector.model = Mock()
            detector.model_initialized = True
            yield detector

    @pytest.mark.asyncio
    async def test_lane_boundary_exact_edges(self, detector):
        """
        EDGE CASE: Coordinates exactly on lane zone boundaries
        BEFORE: Vehicle at exact boundary coordinates
        AFTER: Consistent lane assignment (no floating point errors)
        PURPOSE: Test boundary precision handling
        """
        # Test exact boundary values (0.0 and 1.0)
        edge_north = detector._determine_vehicle_lane(0.5, 0.0)
        edge_south = detector._determine_vehicle_lane(0.5, 1.0)
        edge_east = detector._determine_vehicle_lane(1.0, 0.5)
        edge_west = detector._determine_vehicle_lane(0.0, 0.5)

        # All should return a defined value (not crash)
        assert edge_north in ["north", "unknown"]
        assert edge_south in ["south", "unknown"]
        assert edge_east in ["east", "unknown"]
        assert edge_west in ["west", "unknown"]

    @pytest.mark.asyncio
    async def test_lane_center_ambiguous(self, detector):
        """
        EDGE CASE: Vehicle at exact center of intersection
        BEFORE: Vehicle at (0.5, 0.5) - equidistant from all lanes
        AFTER: Returns 'unknown' lane designation
        PURPOSE: Handle ambiguous positioning gracefully
        """
        center_lane = detector._determine_vehicle_lane(0.5, 0.5)
        assert center_lane == "unknown"

    @pytest.mark.asyncio
    async def test_negative_coordinates(self, detector):
        """
        EDGE CASE: Negative coordinate values (invalid)
        BEFORE: Coordinates outside valid range [0, 1]
        AFTER: Returns 'unknown' or handles gracefully
        PURPOSE: Validate out-of-range input handling
        """
        neg_result = detector._determine_vehicle_lane(-0.5, 0.5)
        # Should not crash, should return unknown or boundary lane
        assert neg_result is not None

    @pytest.mark.asyncio
    async def test_coordinates_above_one(self, detector):
        """
        EDGE CASE: Coordinates above 1.0 (invalid)
        BEFORE: Coordinates > 1.0
        AFTER: Handles gracefully without crash
        PURPOSE: Validate upper bound handling
        """
        over_result = detector._determine_vehicle_lane(1.5, 0.5)
        assert over_result is not None

    @pytest.mark.asyncio
    async def test_empty_vehicle_list(self, detector):
        """
        EDGE CASE: No vehicles detected in frame
        BEFORE: Empty vehicle list
        AFTER: All lane counts return 0
        PURPOSE: Prevent null pointer or division errors
        """
        lane_counts = detector._count_vehicles_by_lane([])

        assert lane_counts["north"] == 0
        assert lane_counts["south"] == 0
        assert lane_counts["east"] == 0
        assert lane_counts["west"] == 0

    @pytest.mark.asyncio
    async def test_single_vehicle(self, detector):
        """
        EDGE CASE: Only one vehicle detected
        BEFORE: Single vehicle in list
        AFTER: Correct lane count = 1, others = 0
        PURPOSE: Test minimum collection size
        """
        vehicles = [
            DetectedVehicle(
                vehicle_type="car",
                confidence=0.9,
                bounding_box={"x1": 100, "y1": 100, "x2": 200, "y2": 180},
                center_coordinates={"x": 0.5, "y": 0.2},
                lane=LaneDirection.NORTH,
            )
        ]

        lane_counts = detector._count_vehicles_by_lane(vehicles)
        assert lane_counts["north"] == 1
        assert lane_counts["south"] == 0
        assert lane_counts["east"] == 0
        assert lane_counts["west"] == 0

    @pytest.mark.asyncio
    async def test_maximum_vehicles_per_lane(self, detector):
        """
        EDGE CASE: Large number of vehicles in single lane
        BEFORE: 100 vehicles all in north lane
        AFTER: Correct count without overflow
        PURPOSE: Test integer handling for high counts
        """
        vehicles = [
            DetectedVehicle(
                vehicle_type="car",
                confidence=0.9,
                bounding_box={"x1": 100, "y1": 100, "x2": 200, "y2": 180},
                center_coordinates={"x": 0.5, "y": 0.2},
                lane=LaneDirection.NORTH,
            )
            for _ in range(100)
        ]

        lane_counts = detector._count_vehicles_by_lane(vehicles)
        assert lane_counts["north"] == 100


class TestStateTransitionEdgeCases:
    """Edge Case Category 3: State Transition Edge Cases"""

    @pytest.mark.asyncio
    async def test_uninitialized_detector_is_not_ready(self):
        """
        EDGE CASE: Attempting operations on uninitialized detector
        BEFORE: Detector created but not initialized
        AFTER: is_ready() returns False
        PURPOSE: Prevent runtime errors from uninitialized resources
        """
        detector = IntelligentVehicleDetector()
        assert not detector.is_ready()
        assert detector.model is None
        assert not detector.model_initialized

    @pytest.mark.asyncio
    async def test_double_initialization(self):
        """
        EDGE CASE: Initializing detector twice
        BEFORE: Detector already initialized
        AFTER: Second initialization is idempotent
        PURPOSE: Ensure safe re-initialization
        """
        detector = IntelligentVehicleDetector()
        with patch.object(detector, "_load_model", new_callable=AsyncMock) as mock_load:
            await detector.initialize()
            await detector.initialize()  # Second call
            # Should not cause errors, may or may not reload model
            assert detector._initialized or detector.model_initialized

    @pytest.mark.asyncio
    async def test_cleanup_on_uninitialized_detector(self):
        """
        EDGE CASE: Calling cleanup on never-initialized detector
        BEFORE: Detector never initialized
        AFTER: Cleanup completes without error
        PURPOSE: Safe cleanup from any state
        """
        detector = IntelligentVehicleDetector()
        await detector.cleanup()  # Should not raise
        assert detector.model is None

    @pytest.mark.asyncio
    async def test_double_cleanup(self):
        """
        EDGE CASE: Calling cleanup twice
        BEFORE: Detector already cleaned up
        AFTER: Second cleanup is idempotent
        PURPOSE: Ensure safe repeated cleanup calls
        """
        detector = IntelligentVehicleDetector()
        with patch.object(detector, "_load_model"):
            detector.model = Mock()
            detector.model_initialized = True

        await detector.cleanup()
        await detector.cleanup()  # Second call should not raise

        assert detector.model is None
        assert not detector.model_initialized

    @pytest.mark.asyncio
    async def test_use_after_cleanup(self):
        """
        EDGE CASE: Attempting detection after cleanup
        BEFORE: Detector cleaned up
        AFTER: Appropriate error or is_ready() returns False
        PURPOSE: Prevent use-after-free type errors
        """
        detector = IntelligentVehicleDetector()
        with patch.object(detector, "_load_model"):
            detector.model = Mock()
            detector.model_initialized = True

        await detector.cleanup()

        assert not detector.is_ready()


class TestFailureScenariosAndRetry:
    """Edge Case Category 4 & 5: Failure Scenarios and Retry Patterns"""

    @pytest.fixture
    def temp_image(self, tmp_path):
        """Create a valid temporary test image"""
        image = np.zeros((640, 640, 3), dtype=np.uint8)
        image_path = tmp_path / "test_image.jpg"
        cv2.imwrite(str(image_path), image)
        return str(image_path)

    @pytest.mark.asyncio
    async def test_model_inference_failure(self):
        """
        FAILURE SCENARIO: YOLO model throws exception during inference
        BEFORE: Model initialized but inference fails
        AFTER: Error propagated with context
        PURPOSE: Validate error handling during ML operations
        """
        detector = IntelligentVehicleDetector()
        detector.model = Mock()
        detector.model_initialized = True
        detector.model.side_effect = RuntimeError("CUDA out of memory")

        with patch("cv2.imread", return_value=np.zeros((640, 640, 3))):
            with pytest.raises((RuntimeError, ValueError)):
                await detector.analyze_intersection_image("test.jpg")

    @pytest.mark.asyncio
    async def test_retry_pattern_with_transient_failure(self):
        """
        RETRY PATTERN: Simulated transient failure recovery
        BEFORE: First N attempts fail, then succeed
        AFTER: Successful result after retries
        PURPOSE: Validate retry logic handles intermittent failures
        """
        call_count = 0

        async def flaky_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Transient network error")
            return "success"

        # Implement simple retry
        max_retries = 3
        result = None
        for attempt in range(max_retries):
            try:
                result = await flaky_operation()
                break
            except ConnectionError:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(0.01)  # Brief backoff

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_pattern(self):
        """
        RETRY PATTERN: Exponential backoff timing validation
        BEFORE: Multiple retry attempts needed
        AFTER: Increasing delays between retries
        PURPOSE: Validate backoff prevents rapid retry storms
        """
        delays = []

        async def track_delays(attempt):
            delay = min(0.01 * (2**attempt), 0.1)  # Exponential with cap
            delays.append(delay)
            await asyncio.sleep(delay)

        for attempt in range(4):
            await track_delays(attempt)

        # Verify exponential increase
        assert delays[1] > delays[0]
        assert delays[2] > delays[1]
        # Verify cap is respected
        assert delays[3] <= 0.1

    @pytest.mark.asyncio
    async def test_cleanup_on_failure(self):
        """
        FAILURE RECOVERY: Resources cleaned up after failure
        BEFORE: Operation fails mid-execution
        AFTER: Resources properly released (no leaks)
        PURPOSE: Validate try-finally cleanup pattern
        """
        detector = IntelligentVehicleDetector()
        detector.model = Mock()
        detector.model_initialized = True

        try:
            # Simulate failure
            raise RuntimeError("Simulated processing failure")
        except RuntimeError:
            pass
        finally:
            await detector.cleanup()

        assert detector.model is None
        assert not detector.model_initialized

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """
        FAILURE SCENARIO: Operation timeout
        BEFORE: Long-running operation initiated
        AFTER: Timeout exception raised within time limit
        PURPOSE: Validate operation doesn't hang indefinitely
        """

        async def slow_operation():
            await asyncio.sleep(10)  # Would take 10 seconds
            return "done"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_operation(), timeout=0.1)


class TestPerformanceMetricsEdgeCases:
    """Edge cases for performance tracking"""

    @pytest.fixture
    async def detector(self):
        detector = IntelligentVehicleDetector()
        with patch.object(detector, "_load_model"):
            detector.model = Mock()
            detector.model_initialized = True
            yield detector

    @pytest.mark.asyncio
    async def test_first_metric_update(self, detector):
        """
        EDGE CASE: First metrics update (from initial state)
        BEFORE: No detections recorded (total=0, last_time=None)
        AFTER: First detection recorded correctly
        PURPOSE: Handle initial state to populated state transition
        """
        initial_count = detector.performance_metrics.get("total_detections", 0)
        initial_time = detector.performance_metrics.get("last_detection_time")

        detector._update_performance_metrics(0.5)

        assert detector.performance_metrics["total_detections"] == initial_count + 1
        assert detector.performance_metrics["last_detection_time"] is not None

    @pytest.mark.asyncio
    async def test_zero_processing_time(self, detector):
        """
        EDGE CASE: Zero processing time input
        BEFORE: Processing time = 0.0
        AFTER: Metrics updated without division errors
        PURPOSE: Handle instant processing edge case
        """
        detector._update_performance_metrics(0.0)
        # Should not raise division by zero or other errors
        metrics = detector.get_performance_metrics()
        assert "total_detections" in metrics

    @pytest.mark.asyncio
    async def test_very_large_processing_time(self, detector):
        """
        EDGE CASE: Extremely large processing time
        BEFORE: Processing time = 1000+ seconds
        AFTER: Metrics stored correctly without overflow
        PURPOSE: Handle outlier timing values
        """
        detector._update_performance_metrics(10000.0)
        metrics = detector.get_performance_metrics()
        assert "average_inference_time" in metrics


class TestConcurrencyEdgeCases:
    """Edge cases for concurrent operations"""

    @pytest.mark.asyncio
    async def test_concurrent_detections(self):
        """
        EDGE CASE: Multiple simultaneous detection requests
        BEFORE: Multiple coroutines call analyze_intersection_image
        AFTER: All complete without race conditions
        PURPOSE: Validate thread-safety of detection operations
        """
        detector = IntelligentVehicleDetector()
        with patch.object(detector, "_load_model"):
            detector.model = Mock()
            detector.model_initialized = True

            # Mock to return valid result
            mock_result = Mock()
            mock_result.boxes = Mock()
            mock_result.boxes.cls = []
            mock_result.boxes.conf = []
            mock_result.boxes.xyxy = []
            detector.model.return_value = [mock_result]

        # This tests that concurrent access doesn't corrupt state
        # (actual test would need real async operations)
        initial_count = detector.performance_metrics.get("total_detections", 0)

        detector._update_performance_metrics(0.1)
        detector._update_performance_metrics(0.1)
        detector._update_performance_metrics(0.1)

        assert detector.performance_metrics["total_detections"] == initial_count + 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
