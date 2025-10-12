"""
Tests for Intelligent Vehicle Detector
Comprehensive testing of YOLOv8 vehicle detection functionality
"""

import pytest
import asyncio
from unittest.mock import Mock, patch
from pathlib import Path
import cv2
import numpy as np

from app.services.intelligent_vehicle_detector import IntelligentVehicleDetector
from app.models.traffic_models import VehicleDetectionResult, DetectedVehicle, LaneDirection
from app.core.config import settings


class TestIntelligentVehicleDetector:
    """Test suite for IntelligentVehicleDetector"""
    
    @pytest.fixture
    async def detector(self):
        """Create detector instance for testing"""
        detector = IntelligentVehicleDetector()
        # Mock the model initialization to avoid downloading YOLO weights
        with patch.object(detector, '_load_model'):
            detector.model = Mock()
            detector.model_initialized = True
            yield detector
    
    @pytest.fixture
    def sample_image(self, test_output_dir):
        """Create a sample test image"""
        # Create a simple test image
        image = np.zeros((640, 640, 3), dtype=np.uint8)
        # Add some colored rectangles to simulate vehicles
        cv2.rectangle(image, (100, 100), (200, 180), (255, 0, 0), -1)  # Blue vehicle
        cv2.rectangle(image, (300, 300), (400, 380), (0, 255, 0), -1)  # Green vehicle
        
        image_path = test_output_dir / "test_traffic.jpg"
        cv2.imwrite(str(image_path), image)
        return str(image_path)
    
    def test_detector_initialization(self):
        """Test detector initialization"""
        detector = IntelligentVehicleDetector()
        assert detector.model is None
        assert not detector.model_initialized
        assert detector.VEHICLE_CLASSES is not None
        assert detector.LANE_ZONES is not None
    
    async def test_detector_ready_state(self, detector):
        """Test detector ready state checking"""
        assert detector.is_ready()
        
        detector.model_initialized = False
        assert not detector.is_ready()
    
    async def test_analyze_intersection_image_mock(self, detector, sample_image):
        """Test vehicle detection with mocked YOLO results"""
        # Mock YOLO detection results
        mock_result = Mock()
        mock_boxes = Mock()
        
        # Simulate two vehicle detections
        mock_boxes.cls = [Mock(), Mock()]
        mock_boxes.cls[0].item.return_value = 2  # Car class
        mock_boxes.cls[1].item.return_value = 7  # Truck class
        
        mock_boxes.conf = [Mock(), Mock()]
        mock_boxes.conf[0].item.return_value = 0.85
        mock_boxes.conf[1].item.return_value = 0.72
        
        mock_boxes.xyxy = [Mock(), Mock()]
        mock_boxes.xyxy[0].tolist.return_value = [100, 100, 200, 180]
        mock_boxes.xyxy[1].tolist.return_value = [300, 300, 400, 380]
        
        mock_result.boxes = mock_boxes
        detector.model.return_value = [mock_result]
        
        # Test detection
        result = await detector.analyze_intersection_image(sample_image)
        
        assert isinstance(result, VehicleDetectionResult)
        assert result.total_vehicles == 2
        assert len(result.detected_vehicles) == 2
        assert result.image_path == sample_image
        assert result.processing_time > 0
    
    def test_determine_vehicle_lane(self, detector):
        """Test lane determination logic"""
        # Test center coordinates for each lane
        north_lane = detector._determine_vehicle_lane(0.5, 0.2)  # Top center
        assert north_lane == 'north'
        
        south_lane = detector._determine_vehicle_lane(0.5, 0.8)  # Bottom center
        assert south_lane == 'south'
        
        east_lane = detector._determine_vehicle_lane(0.8, 0.5)  # Right center
        assert east_lane == 'east'
        
        west_lane = detector._determine_vehicle_lane(0.2, 0.5)  # Left center
        assert west_lane == 'west'
        
        # Test unknown lane (center)
        unknown_lane = detector._determine_vehicle_lane(0.5, 0.5)
        assert unknown_lane == 'unknown'
    
    def test_count_vehicles_by_lane(self, detector):
        """Test vehicle counting by lane"""
        # Create test detected vehicles
        vehicles = [
            DetectedVehicle(
                vehicle_type='car',
                confidence=0.8,
                bounding_box={'x1': 100, 'y1': 100, 'x2': 200, 'y2': 180},
                center_coordinates={'x': 0.5, 'y': 0.2},
                lane=LaneDirection.NORTH
            ),
            DetectedVehicle(
                vehicle_type='truck',
                confidence=0.7,
                bounding_box={'x1': 300, 'y1': 300, 'x2': 400, 'y2': 380},
                center_coordinates={'x': 0.8, 'y': 0.5},
                lane=LaneDirection.EAST
            )
        ]
        
        lane_counts = detector._count_vehicles_by_lane(vehicles)
        
        assert lane_counts['north'] == 1
        assert lane_counts['east'] == 1
        assert lane_counts['south'] == 0
        assert lane_counts['west'] == 0
    
    async def test_save_annotated_image(self, detector, sample_image, test_output_dir):
        """Test annotated image saving"""
        image = cv2.imread(sample_image)
        
        vehicles = [
            DetectedVehicle(
                vehicle_type='car',
                confidence=0.8,
                bounding_box={'x1': 100, 'y1': 100, 'x2': 200, 'y2': 180},
                center_coordinates={'x': 0.3, 'y': 0.3},
                lane=LaneDirection.NORTH
            )
        ]
        
        output_path = await detector._save_annotated_image(
            image, vehicles, sample_image
        )
        
        assert output_path is not None
        assert Path(output_path).exists()
    
    def test_update_performance_metrics(self, detector):
        """Test performance metrics updating"""
        initial_count = detector.performance_metrics['total_detections']
        
        detector._update_performance_metrics(0.5)
        
        assert detector.performance_metrics['total_detections'] == initial_count + 1
        assert detector.performance_metrics['last_detection_time'] is not None
    
    def test_get_performance_metrics(self, detector):
        """Test performance metrics retrieval"""
        metrics = detector.get_performance_metrics()
        
        assert 'total_detections' in metrics
        assert 'average_inference_time' in metrics
        assert 'last_detection_time' in metrics
        assert isinstance(metrics, dict)
    
    async def test_cleanup(self, detector):
        """Test detector cleanup"""
        await detector.cleanup()
        
        assert detector.model is None
        assert not detector.model_initialized
    
    async def test_invalid_image_path(self, detector):
        """Test handling of invalid image path"""
        with pytest.raises(ValueError, match="Could not load image"):
            await detector.analyze_intersection_image("nonexistent_image.jpg")
    
    def test_vehicle_classes_mapping(self, detector):
        """Test vehicle class mapping"""
        assert 2 in detector.VEHICLE_CLASSES  # car
        assert detector.VEHICLE_CLASSES[2] == 'car'
        assert detector.VEHICLE_CLASSES[7] == 'truck'
    
    def test_lane_zones_configuration(self, detector):
        """Test lane zones configuration"""
        zones = detector.LANE_ZONES
        
        assert 'north' in zones
        assert 'south' in zones
        assert 'east' in zones
        assert 'west' in zones
        
        # Check zone coordinates are valid
        for zone_name, zone in zones.items():
            assert 0 <= zone['x_min'] <= 1
            assert 0 <= zone['x_max'] <= 1
            assert 0 <= zone['y_min'] <= 1
            assert 0 <= zone['y_max'] <= 1
            assert zone['x_min'] < zone['x_max']
            assert zone['y_min'] < zone['y_max']


@pytest.mark.integration
class TestVehicleDetectorIntegration:
    """Integration tests for vehicle detector (require model download)"""
    
    @pytest.mark.skip(reason="Requires YOLO model download - enable for full integration testing")
    async def test_real_model_initialization(self):
        """Test real YOLOv8 model initialization"""
        detector = IntelligentVehicleDetector()
        await detector.initialize()
        
        assert detector.is_ready()
        assert detector.model is not None
        
        await detector.cleanup()
    
    @pytest.mark.skip(reason="Requires YOLO model and test images - enable for full integration testing")
    async def test_real_vehicle_detection(self, sample_image):
        """Test real vehicle detection with actual model"""
        detector = IntelligentVehicleDetector()
        await detector.initialize()
        
        try:
            result = await detector.analyze_intersection_image(sample_image)
            
            assert isinstance(result, VehicleDetectionResult)
            assert result.total_vehicles >= 0
            assert result.processing_time > 0
            assert len(result.lane_counts) == 4
            
        finally:
            await detector.cleanup()
