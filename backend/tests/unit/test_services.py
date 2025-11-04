"""Unit tests for service classes"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, AsyncMock
import asyncio
from pathlib import Path

from app.services.intelligent_vehicle_detector import IntelligentVehicleDetector
from app.services.adaptive_traffic_manager import AdaptiveTrafficManager
from app.services.analytics_service import TrafficAnalyticsService
from app.models.traffic_models import VehicleDetectionResult, IntersectionStatus


class TestIntelligentVehicleDetector:
    """Test vehicle detection service"""
    
    @pytest.fixture
    async def detector(self):
        """Create detector instance with mocked dependencies"""
        with patch('app.services.intelligent_vehicle_detector.IntelligentVehicleDetector._load_model', new_callable=Mock) as mock_load_model:
            mock_load_model.return_value = Mock()  # Simulate the YOLO model object
            detector = IntelligentVehicleDetector()
            await detector.initialize()
            yield detector
    
    @pytest.mark.asyncio
    async def test_initialization(self, detector):
        """Test detector initialization"""
        assert detector.is_ready()
    
    @pytest.mark.asyncio
    async def test_analyze_intersection_image(self, detector):
        """Test image analysis"""
        # Setup
        detector.model = Mock()
        detector.model.return_value = []
        
        with patch('cv2.imread') as mock_imread, \
             patch('cv2.imwrite') as mock_imwrite:
            
            # Mock image loading
            mock_imread.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
            mock_imwrite.return_value = True
            
            # Test analysis
            result = await detector.analyze_intersection_image("fake_path")
            
            # Assertions
            assert isinstance(result, VehicleDetectionResult)
            assert result.total_vehicles >= 0
            assert isinstance(result.lane_counts, dict)
    
    @pytest.mark.asyncio
    async def test_cleanup(self, detector):
        """Test cleanup process"""
        await detector.cleanup()
        assert not detector.is_ready()

    @pytest.mark.asyncio
    async def test_analyze_intersection_image_with_none_path(self, detector):
        """Test image analysis with a None path"""
        with pytest.raises(ValueError):
            await detector.analyze_intersection_image(None)


class TestAdaptiveTrafficManager:
    """Test traffic management service"""
    
    @pytest.fixture
    def manager(self):
        """Create manager instance"""
        return AdaptiveTrafficManager()
    
    @pytest.mark.asyncio
    async def test_initialization(self, manager):
        """Test manager initialization"""
        await manager.initialize()
        assert manager.is_ready()
    
    @pytest.mark.asyncio
    async def test_get_current_status(self, manager):
        """Test getting current intersection status"""
        await manager.initialize()
        
        status = await manager.get_current_status()
        
        assert isinstance(status, IntersectionStatus)
        assert isinstance(status.vehicle_counts, dict)
    
    @pytest.mark.asyncio
    async def test_update_vehicle_counts(self, manager):
        """Test updating vehicle counts"""
        await manager.initialize()
        
        lane_counts = {'north': 5, 'south': 3, 'east': 2, 'west': 1}
        await manager.update_vehicle_counts(lane_counts)
        
        status = await manager.get_current_status()
        assert status.vehicle_counts == lane_counts
    
    @pytest.mark.asyncio
    async def test_cleanup(self, manager):
        """Test cleanup process"""
        await manager.initialize()
        await manager.cleanup()
        
        assert not manager.is_ready()


class TestTrafficAnalyticsService:
    """Test analytics service"""
    
    @pytest.fixture
    def analytics(self):
        """Create analytics service instance"""
        return TrafficAnalyticsService()
    
    @pytest.mark.asyncio
    async def test_initialization(self, analytics):
        """Test analytics initialization"""
        await analytics.initialize()
        assert analytics.is_ready()
    
    @pytest.mark.asyncio
    async def test_record_detection(self, analytics):
        """Test recording detection data"""
        await analytics.initialize()
        
        from datetime import datetime
        timestamp = datetime.utcnow()
        
        detection_result = Mock()
        detection_result.total_vehicles = 10
        detection_result.lane_counts = {'north': 5, 'south': 5}
        
        await analytics.record_detection(detection_result, timestamp)
        
        summary = await analytics.generate_summary('current')
        assert summary['detection_count'] == 1
    
    @pytest.mark.asyncio
    async def test_cleanup(self, analytics):
        """Test cleanup process"""
        await analytics.initialize()
        await analytics.cleanup()
        assert not analytics.is_ready()
