"""
Test suite for health check system
Tests health endpoint functionality and service status validation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from datetime import datetime, timezone


@pytest.fixture
def mock_services():
    """Mock services for testing"""
    vehicle_detector = AsyncMock()
    vehicle_detector.is_ready.return_value = True
    
    traffic_manager = AsyncMock()
    traffic_manager.is_ready.return_value = True
    
    analytics_service = AsyncMock()
    analytics_service.is_ready.return_value = True
    
    return vehicle_detector, traffic_manager, analytics_service


class TestHealthEndpoint:
    """Test health check endpoint functionality"""
    
    @patch('app.main.vehicle_detector')
    @patch('app.main.traffic_manager')
    @patch('app.main.analytics_service')
    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    def test_health_check_all_services_healthy(self, mock_memory, mock_cpu, 
                                             mock_analytics, mock_traffic, mock_detector):
        """Test health check when all services are healthy"""
        # Setup mocks
        mock_detector.is_ready.return_value = True
        mock_traffic.is_ready.return_value = True
        mock_analytics.is_ready.return_value = True
        
        mock_cpu.return_value = 25.0
        mock_memory.return_value = MagicMock(percent=60.0, used=8000000000)
        
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "healthy"
        assert data["health_score"] == 1.0
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert data["services"]["vehicle_detector"] is True
        assert data["services"]["traffic_manager"] is True
        assert data["services"]["analytics"] is True
        assert data["system"]["cpu_percent"] == 25.0
        assert data["system"]["memory_percent"] == 60.0
    
    @patch('app.main.vehicle_detector', None)
    @patch('app.main.traffic_manager')
    @patch('app.main.analytics_service')
    def test_health_check_missing_services(self, mock_analytics, mock_traffic):
        """Test health check when some services are missing"""
        mock_traffic.is_ready.return_value = True
        mock_analytics.is_ready.return_value = True
        
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] in ["degraded", "unhealthy"]
        assert data["health_score"] < 1.0
        assert data["services"]["vehicle_detector"] is False
        assert data["services"]["traffic_manager"] is True
        assert data["services"]["analytics"] is True
    
    @patch('app.main.vehicle_detector')
    @patch('app.main.traffic_manager')
    @patch('app.main.analytics_service')
    def test_health_check_services_not_ready(self, mock_analytics, mock_traffic, mock_detector):
        """Test health check when services exist but are not ready"""
        mock_detector.is_ready.return_value = False
        mock_traffic.is_ready.return_value = False
        mock_analytics.is_ready.return_value = False
        
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "unhealthy"
        assert data["health_score"] == 0.0
        assert all(status is False for status in data["services"].values())
    
    @patch('app.main.vehicle_detector')
    @patch('app.main.traffic_manager')
    @patch('app.main.analytics_service')
    @patch('psutil.cpu_percent', side_effect=Exception("CPU unavailable"))
    def test_health_check_system_metrics_failure(self, mock_cpu, mock_analytics, 
                                                mock_traffic, mock_detector):
        """Test health check when system metrics fail"""
        mock_detector.is_ready.return_value = True
        mock_traffic.is_ready.return_value = True
        mock_analytics.is_ready.return_value = True
        
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should still return healthy if services are working
        assert data["status"] == "healthy"
        # System metrics should fallback to defaults
        assert data["system"]["cpu_percent"] == 0.0
        assert data["system"]["memory_percent"] == 0.0
    
    @patch('app.main.vehicle_detector', None)
    @patch('app.main.traffic_manager', None)
    @patch('app.main.analytics_service', None)
    def test_health_check_no_services(self):
        """Test health check when no services are available"""
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "unhealthy"
        assert data["health_score"] == 0.0
        assert all(status is False for status in data["services"].values())
    
    def test_health_check_response_format(self):
        """Test health check response contains all required fields"""
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "status", "timestamp", "uptime_seconds", "health_score",
            "services", "system", "websocket_connections", "version"
        ]
        
        for field in required_fields:
            assert field in data
        
        # Check services structure
        service_fields = ["vehicle_detector", "traffic_manager", "analytics"]
        for field in service_fields:
            assert field in data["services"]
        
        # Check system structure  
        system_fields = ["cpu_percent", "memory_percent", "memory_bytes"]
        for field in system_fields:
            assert field in data["system"]
    
    def test_health_check_timestamp_format(self):
        """Test health check timestamp is in correct ISO format"""
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/health")
        data = response.json()
        
        # Should be able to parse as ISO timestamp
        timestamp = datetime.fromisoformat(data["timestamp"].replace('Z', '+00:00'))
        assert isinstance(timestamp, datetime)
        
        # Should be recent (within last minute)
        now = datetime.now(timezone.utc)
        time_diff = abs((now - timestamp.replace(tzinfo=timezone.utc)).total_seconds())
        assert time_diff < 60  # Within 1 minute


class TestHealthScoring:
    """Test health score calculation logic"""
    
    def test_health_score_all_healthy(self):
        """Test health score when all services are healthy"""
        services = {
            "vehicle_detector": True,
            "traffic_manager": True,
            "analytics": True
        }
        
        healthy_services = sum(1 for status in services.values() if status)
        total_services = len(services)
        health_score = healthy_services / total_services if total_services > 0 else 0.0
        
        assert health_score == 1.0
    
    def test_health_score_partial_healthy(self):
        """Test health score with some services unhealthy"""
        services = {
            "vehicle_detector": True,
            "traffic_manager": False,
            "analytics": True
        }
        
        healthy_services = sum(1 for status in services.values() if status)
        total_services = len(services)
        health_score = healthy_services / total_services if total_services > 0 else 0.0
        
        assert health_score == 2/3  # Approximately 0.67
    
    def test_health_score_none_healthy(self):
        """Test health score when no services are healthy"""
        services = {
            "vehicle_detector": False,
            "traffic_manager": False,
            "analytics": False
        }
        
        healthy_services = sum(1 for status in services.values() if status)
        total_services = len(services)
        health_score = healthy_services / total_services if total_services > 0 else 0.0
        
        assert health_score == 0.0
    
    def test_health_status_classification(self):
        """Test health status classification based on score"""
        # Healthy: score >= 0.8
        assert self._classify_health(1.0) == "healthy"
        assert self._classify_health(0.9) == "healthy"
        assert self._classify_health(0.8) == "healthy"
        
        # Degraded: 0.5 <= score < 0.8
        assert self._classify_health(0.7) == "degraded"
        assert self._classify_health(0.6) == "degraded"
        assert self._classify_health(0.5) == "degraded"
        
        # Unhealthy: score < 0.5
        assert self._classify_health(0.4) == "unhealthy"
        assert self._classify_health(0.2) == "unhealthy"
        assert self._classify_health(0.0) == "unhealthy"
    
    def _classify_health(self, health_score: float) -> str:
        """Helper method to classify health status"""
        if health_score >= 0.8:
            return "healthy"
        elif health_score >= 0.5:
            return "degraded"
        else:
            return "unhealthy"


if __name__ == "__main__":
    pytest.main([__file__])
