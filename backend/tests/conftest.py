"""
Test Configuration and Fixtures for AI Traffic Management System
Comprehensive fixtures for unit and integration testing
"""

import pytest
import asyncio
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime
import numpy as np

# Ensure app modules can be imported
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# ASYNC FIXTURES
# ============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# DIRECTORY FIXTURES
# ============================================================================

@pytest.fixture
def test_output_dir(tmp_path):
    """
    Provides a temporary directory for test outputs.
    Automatically cleaned up after test completion.
    
    Rationale: Tests that save images or other files need isolated directories
    to avoid polluting the source tree and conflicts between tests.
    """
    output_dir = tmp_path / "test_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@pytest.fixture
def temp_image_file(test_output_dir):
    """
    Creates a temporary test image file for vehicle detection tests.
    
    Rationale: Vehicle detection tests need actual image files to process.
    This creates a simple colored image that can be used without external resources.
    """
    try:
        import cv2
        # Create a simple test image (640x480 with some colored rectangles)
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        # Add some rectangles to simulate vehicles
        cv2.rectangle(image, (100, 100), (200, 180), (255, 0, 0), -1)  # Blue rectangle
        cv2.rectangle(image, (300, 200), (400, 280), (0, 255, 0), -1)  # Green rectangle
        cv2.rectangle(image, (450, 300), (550, 380), (0, 0, 255), -1)  # Red rectangle
        
        image_path = test_output_dir / "test_traffic_image.jpg"
        cv2.imwrite(str(image_path), image)
        return str(image_path)
    except ImportError:
        # Fallback if cv2 not available - create a simple file
        image_path = test_output_dir / "test_traffic_image.jpg"
        # Create a minimal valid JPEG header
        image_path.write_bytes(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00')
        return str(image_path)


# ============================================================================
# MOCK EXTERNAL DEPENDENCIES
# ============================================================================

@pytest.fixture
def mock_external_dependencies():
    """
    Mocks all external dependencies (database, Redis, external APIs).
    
    Rationale: Unit tests should be isolated from external services.
    This fixture prevents tests from making real network calls or requiring
    running database instances.
    """
    with patch('motor.motor_asyncio.AsyncIOMotorClient') as mock_mongo, \
         patch('redis.asyncio.Redis') as mock_redis, \
         patch('aiohttp.ClientSession') as mock_http:
        
        # Configure MongoDB mock
        mock_mongo_client = MagicMock()
        mock_mongo_db = MagicMock()
        mock_mongo_collection = MagicMock()
        mock_mongo_collection.find.return_value = AsyncMock(return_value=[])
        mock_mongo_collection.find_one = AsyncMock(return_value=None)
        mock_mongo_collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id="test_id"))
        mock_mongo_collection.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_mongo_db.__getitem__ = MagicMock(return_value=mock_mongo_collection)
        mock_mongo_client.__getitem__ = MagicMock(return_value=mock_mongo_db)
        mock_mongo.return_value = mock_mongo_client
        
        # Configure Redis mock
        mock_redis_instance = AsyncMock()
        mock_redis_instance.get = AsyncMock(return_value=None)
        mock_redis_instance.set = AsyncMock(return_value=True)
        mock_redis_instance.delete = AsyncMock(return_value=1)
        mock_redis_instance.expire = AsyncMock(return_value=True)
        mock_redis_instance.incr = AsyncMock(return_value=1)
        mock_redis.from_url = AsyncMock(return_value=mock_redis_instance)
        
        # Configure HTTP client mock
        mock_http_instance = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={})
        mock_http_instance.get = AsyncMock(return_value=mock_response)
        mock_http_instance.post = AsyncMock(return_value=mock_response)
        mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        mock_http.return_value.__aexit__ = AsyncMock(return_value=None)
        
        yield {
            'mongo': mock_mongo_client,
            'redis': mock_redis_instance,
            'http': mock_http_instance
        }


# ============================================================================
# YOLO MODEL MOCKS
# ============================================================================

@pytest.fixture
def mock_yolo_model():
    """
    Mocks the YOLOv8 model for testing without loading actual weights.
    
    Rationale: Loading YOLOv8 weights takes significant time and memory.
    This mock provides realistic detection results for testing the processing
    pipeline without the overhead of actual model inference.
    """
    mock_model = MagicMock()
    
    # Create mock detection results
    mock_result = MagicMock()
    mock_boxes = MagicMock()
    
    # Simulate 3 vehicle detections
    mock_box_data = [
        {'cls': 2, 'conf': 0.85, 'xyxy': [100, 100, 200, 180]},  # Car
        {'cls': 7, 'conf': 0.72, 'xyxy': [300, 200, 450, 320]},  # Truck
        {'cls': 5, 'conf': 0.91, 'xyxy': [500, 150, 620, 280]},  # Bus
    ]
    
    # Mock the box attributes
    mock_boxes.cls = [MagicMock(item=MagicMock(return_value=box['cls'])) for box in mock_box_data]
    mock_boxes.conf = [MagicMock(item=MagicMock(return_value=box['conf'])) for box in mock_box_data]
    mock_boxes.xyxy = [MagicMock(tolist=MagicMock(return_value=box['xyxy'])) for box in mock_box_data]
    
    # Make the boxes iterable by combining correctly
    mock_boxes.__len__ = MagicMock(return_value=3)
    mock_boxes.__iter__ = MagicMock(return_value=iter(zip(
        mock_boxes.cls,
        mock_boxes.conf, 
        mock_boxes.xyxy
    )))
    
    mock_result.boxes = mock_boxes
    
    # Model call returns list of results
    mock_model.return_value = [mock_result]
    mock_model.names = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}
    
    return mock_model


# ============================================================================
# SAMPLE DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_emergency_alert():
    """
    Provides a sample EmergencyAlert object for testing.
    
    Rationale: Emergency override tests need valid alert objects.
    This provides a realistic emergency alert with all required fields.
    """
    from app.models.traffic_models import EmergencyAlert, EmergencyType, LaneDirection
    
    return EmergencyAlert(
        alert_id="emergency_test_001",
        emergency_type=EmergencyType.AMBULANCE,
        detected_lane=LaneDirection.NORTH,
        vehicle_location={"x": 0.5, "y": 0.2},
        priority_level=5,
        estimated_arrival_time=30,
        override_duration=60,
        is_active=True
    )


@pytest.fixture
def sample_detection_result():
    """
    Provides a sample VehicleDetectionResult for testing.
    
    Rationale: Analytics and manager tests need detection results
    without running actual detection algorithms.
    """
    from app.models.traffic_models import (
        VehicleDetectionResult, DetectedVehicle, 
        VehicleType, LaneDirection
    )
    
    vehicles = [
        DetectedVehicle(
            vehicle_type=VehicleType.CAR,
            confidence=0.85,
            bounding_box={'x1': 100, 'y1': 100, 'x2': 200, 'y2': 180},
            center_coordinates={'x': 0.25, 'y': 0.25},
            lane=LaneDirection.NORTH,
            is_emergency=False
        ),
        DetectedVehicle(
            vehicle_type=VehicleType.TRUCK,
            confidence=0.72,
            bounding_box={'x1': 300, 'y1': 200, 'x2': 450, 'y2': 320},
            center_coordinates={'x': 0.65, 'y': 0.45},
            lane=LaneDirection.EAST,
            is_emergency=False
        ),
    ]
    
    return VehicleDetectionResult(
        total_vehicles=2,
        lane_counts={
            LaneDirection.NORTH: 1,
            LaneDirection.SOUTH: 0,
            LaneDirection.EAST: 1,
            LaneDirection.WEST: 0
        },
        detected_vehicles=vehicles,
        confidence_scores=[0.85, 0.72],
        processing_time=0.150,
        image_path="/tmp/test_image.jpg",
        annotated_image_path="/tmp/test_annotated.jpg",
        has_emergency_vehicles=False,
        traffic_density=0.35
    )


@pytest.fixture
def sample_intersection_status():
    """
    Provides a sample IntersectionStatus for testing.
    """
    from app.models.traffic_models import (
        IntersectionStatus, TrafficSignal, 
        TrafficSignalState, LaneDirection
    )
    
    signals = {
        LaneDirection.NORTH: TrafficSignal(
            signal_id="signal_north",
            direction=LaneDirection.NORTH,
            current_state=TrafficSignalState.GREEN,
            remaining_time=25,
            next_state=TrafficSignalState.YELLOW
        ),
        LaneDirection.SOUTH: TrafficSignal(
            signal_id="signal_south",
            direction=LaneDirection.SOUTH,
            current_state=TrafficSignalState.GREEN,
            remaining_time=25,
            next_state=TrafficSignalState.YELLOW
        ),
        LaneDirection.EAST: TrafficSignal(
            signal_id="signal_east",
            direction=LaneDirection.EAST,
            current_state=TrafficSignalState.RED,
            remaining_time=28,
            next_state=TrafficSignalState.GREEN
        ),
        LaneDirection.WEST: TrafficSignal(
            signal_id="signal_west",
            direction=LaneDirection.WEST,
            current_state=TrafficSignalState.RED,
            remaining_time=28,
            next_state=TrafficSignalState.GREEN
        ),
    }
    
    return IntersectionStatus(
        intersection_id="main_intersection",
        traffic_signals=signals,
        vehicle_counts={
            LaneDirection.NORTH: 5,
            LaneDirection.SOUTH: 3,
            LaneDirection.EAST: 8,
            LaneDirection.WEST: 2
        },
        total_vehicles=18,
        traffic_flow_rate=45.5,
        average_wait_time=12.3,
        emergency_mode_active=False,
        system_status="operational"
    )


# ============================================================================
# TEST CLIENT FIXTURES
# ============================================================================

@pytest.fixture
def test_client():
    """
    Provides a FastAPI TestClient for API testing.
    
    Rationale: Integration tests need to make HTTP requests to the API.
    TestClient provides a synchronous interface for testing async endpoints.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    
    with TestClient(app) as client:
        yield client


@pytest.fixture
async def async_test_client():
    """
    Provides an async HTTP client for async API testing.
    """
    import httpx
    from app.main import app
    
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        yield client


# ============================================================================
# CONFIGURATION FIXTURES
# ============================================================================

@pytest.fixture
def test_settings():
    """
    Provides test-specific settings overrides.
    """
    from app.core.config import TestingSettings
    return TestingSettings()


@pytest.fixture(autouse=True)
def reset_settings():
    """
    Resets settings cache before each test.
    
    Rationale: Settings are cached with @lru_cache. Tests may modify
    environment variables, so the cache must be cleared to ensure
    test isolation.
    """
    from app.core.config import get_application_settings
    get_application_settings.cache_clear()
    yield
    get_application_settings.cache_clear()


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (may require external services)"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "requires_model: mark test as requiring actual YOLO model"
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless explicitly requested."""
    if not config.getoption("--run-integration", default=False):
        skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests"
    )
