"""Unit tests for vehicle detector"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from app.services.intelligent_vehicle_detector import IntelligentVehicleDetector


@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for each test module."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def detector(event_loop):
    """Provides a detector instance for tests."""
    
    async def setup_detector():
        with patch.object(IntelligentVehicleDetector, '_load_model') as mock_load:
            d = IntelligentVehicleDetector()
            await d.initialize()
            return d

    detector = event_loop.run_until_complete(setup_detector())
    yield detector
    
    # Cleanup
    async def cleanup_detector():
        await detector.cleanup()
        
    event_loop.run_until_complete(cleanup_detector())


class TestIntelligentVehicleDetector:
    """Tests for the IntelligentVehicleDetector service."""

    def test_initialization(self, detector):
        """Test detector initialization."""
        assert detector.is_ready()

    @patch('cv2.imread')
    @patch('cv2.imwrite')
    def test_analyze_intersection_image(self, mock_imwrite, mock_imread, detector):
        """Test intersection image analysis."""
        
        # Mocking
        mock_imread.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
        
        # Mock the model's return value for detection
        detector.model = Mock()
        detector.model.return_value = []

        # Test
        result = asyncio.run(detector.analyze_intersection_image("fake_path.jpg"))

        assert result is not None
        assert result.total_vehicles == 0

    def test_invalid_image(self, detector):
        """Test handling of an invalid image."""
        with pytest.raises(ValueError, match="Image path cannot be None or empty."):
            asyncio.run(detector.analyze_intersection_image(None))
