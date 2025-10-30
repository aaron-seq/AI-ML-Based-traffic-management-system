"""Unit tests for service classes"""

import pytest
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
    def detector(self, mock_external_dependencies):
        """Create detector instance with mocked dependencies"""
        return IntelligentVehicleDetector()
    
    @pytest.mark.asyncio
    async def test_initialization(self, detector):
        """Test detector initialization"""
        with patch.object(detector, '_load_model', new_callable=AsyncMock) as mock_load:
            await detector.initialize()
            mock_load.assert_called_once()
            assert detector._initialized
    
    @pytest.mark.asyncio
    async def test_analyze_intersection_image(self, detector, temp_image_file, mock_yolo_model):
        """Test image analysis"""
        # Setup
        detector._model = mock_yolo_model
        detector._initialized = True
        
        with patch('cv2.imread') as mock_imread, \
             patch('cv2.imwrite') as mock_imwrite:
            
            # Mock image loading
            mock_imread.return_value = [[1, 2, 3]]  # Fake image array
            mock_imwrite.return_value = True
            
            # Test analysis
            result = await detector.analyze_intersection_image(temp_image_file)
            
            # Assertions
            assert isinstance(result, VehicleDetectionResult)
            assert result.total_vehicles >= 0
            assert isinstance(result.lane_counts, dict)
            assert isinstance(result.processing_time, float)
    
    def test_is_ready(self, detector):
        """Test readiness check"""
        assert not detector.is_ready()
        
        detector._initialized = True
        detector._model = Mock()
        assert detector.is_ready()
    
    @pytest.mark.asyncio
    async def test_cleanup(self, detector):
        """Test cleanup process"""
        detector._model = Mock()
        detector._initialized = True
        
        await detector.cleanup()
        
        assert not detector._initialized
        assert detector._model is None


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
        assert status.intersection_id
        assert status.current_phase
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
    async def test_emergency_override(self, manager, sample_emergency_alert):
        """Test emergency override functionality"""
        await manager.initialize()
        
        await manager.handle_emergency_override(sample_emergency_alert)
        
        status = await manager.get_current_status()
        assert status.emergency_override_active
    
    @pytest.mark.asyncio
    async def test_start_stop_simulation(self, manager):
        """Test simulation start/stop"""
        await manager.initialize()
        
        await manager.start_simulation()
        # Simulation should be running
        
        await manager.stop_simulation()
        # Simulation should be stopped
    
    @pytest.mark.asyncio
    async def test_cleanup(self, manager):
        """Test cleanup process"""
        await manager.initialize()
        await manager.cleanup()
        
        assert not manager.is_ready()


class TestTrafficAnalyticsService:
    """Test analytics service"""
    
    @pytest.fixture
    def analytics(self, mock_external_dependencies):
        """Create analytics service instance"""
        return TrafficAnalyticsService()
    
    @pytest.mark.asyncio
    async def test_initialization(self, analytics):
        """Test analytics initialization"""
        with patch.object(analytics, '_connect_database', new_callable=AsyncMock):
            await analytics.initialize()
            assert analytics.is_ready()
    
    @pytest.mark.asyncio
    async def test_record_detection(self, analytics, sample_detection_result):
        """Test recording detection data"""
        await analytics.initialize()
        
        from datetime import datetime
        timestamp = datetime.utcnow()
        
        with patch.object(analytics, '_store_detection_data', new_callable=AsyncMock) as mock_store:
            await analytics.record_detection(sample_detection_result, timestamp)
            mock_store.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_generate_summary(self, analytics):
        """Test generating analytics summary"""
        await analytics.initialize()
        
        with patch.object(analytics, '_calculate_summary', new_callable=AsyncMock) as mock_calc:
            mock_calc.return_value = {
                'total_detections': 100,
                'average_vehicles_per_hour': 45,
                'efficiency_score': 0.85
            }
            
            summary = await analytics.generate_summary('daily')
            
            assert 'total_detections' in summary
            assert 'efficiency_score' in summary
            mock_calc.assert_called_once_with('daily')
    
    @pytest.mark.asyncio
    async def test_get_traffic_heatmap_data(self, analytics):
        """Test getting heatmap data"""
        await analytics.initialize()
        
        with patch.object(analytics, '_generate_heatmap', new_callable=AsyncMock) as mock_heatmap:
            mock_heatmap.return_value = {
                'heatmap_data': [[1, 2], [3, 4]],
                'time_labels': ['08:00', '09:00'],
                'lane_labels': ['north', 'south']
            }
            
            heatmap = await analytics.get_traffic_heatmap_data(24)
            
            assert 'heatmap_data' in heatmap
            assert 'time_labels' in heatmap
            mock_heatmap.assert_called_once_with(24)
    
    @pytest.mark.asyncio
    async def test_get_performance_report(self, analytics):
        """Test getting performance report"""
        await analytics.initialize()
        
        with patch.object(analytics, '_calculate_performance', new_callable=AsyncMock) as mock_perf:
            mock_perf.return_value = {
                'uptime': '99.9%',
                'average_response_time': 150,
                'total_requests': 1000,
                'error_rate': 0.1
            }
            
            report = await analytics.get_performance_report()
            
            assert 'uptime' in report
            assert 'average_response_time' in report
            mock_perf.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup(self, analytics):
        """Test cleanup process"""
        await analytics.initialize()
        
        with patch.object(analytics, '_disconnect_database', new_callable=AsyncMock) as mock_disconnect:
            await analytics.cleanup()
            mock_disconnect.assert_called_once()
            assert not analytics.is_ready()


class TestServiceIntegration:
    """Test service integration and communication"""
    
    @pytest.mark.asyncio
    async def test_detector_manager_integration(self, mock_external_dependencies):
        """Test integration between detector and manager"""
        detector = IntelligentVehicleDetector()
        manager = AdaptiveTrafficManager()
        
        # Initialize both services
        with patch.object(detector, '_load_model', new_callable=AsyncMock):
            await detector.initialize()
        await manager.initialize()
        
        # Mock detection result
        detection_result = Mock()
        detection_result.lane_counts = {'north': 5, 'south': 3, 'east': 2, 'west': 1}
        
        # Test integration
        await manager.update_vehicle_counts(detection_result.lane_counts)
        
        status = await manager.get_current_status()
        assert status.vehicle_counts == detection_result.lane_counts
    
    @pytest.mark.asyncio
    async def test_manager_analytics_integration(self, mock_external_dependencies):
        """Test integration between manager and analytics"""
        manager = AdaptiveTrafficManager()
        analytics = TrafficAnalyticsService()
        
        # Initialize services
        await manager.initialize()
        with patch.object(analytics, '_connect_database', new_callable=AsyncMock):
            await analytics.initialize()
        
        # Test data flow
        detection_result = Mock()
        detection_result.total_vehicles = 10
        detection_result.lane_counts = {'north': 5, 'south': 5}
        
        from datetime import datetime
        timestamp = datetime.utcnow()
        
        with patch.object(analytics, '_store_detection_data', new_callable=AsyncMock) as mock_store:
            await analytics.record_detection(detection_result, timestamp)
            mock_store.assert_called_once()


if __name__ == "__main__":
    pytest.main(["-v", __file__])
