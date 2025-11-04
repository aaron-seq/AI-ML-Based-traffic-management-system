"""Unit tests for health check endpoint"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app, vehicle_detector, traffic_manager, analytics_service


@pytest.fixture(scope="module")
def client():
    """Provides a TestClient instance for the API tests."""
    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    @patch.object(vehicle_detector, 'is_ready', return_value=True)
    @patch.object(traffic_manager, 'is_ready', return_value=True)
    @patch.object(analytics_service, 'is_ready', return_value=True)
    def test_health_check_all_services_healthy(self, mock_analytics, mock_traffic, mock_vehicle, client):
        """Test health check when all services are healthy."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["services"]["vehicle_detector"] is True
        assert data["services"]["traffic_manager"] is True
        assert data["services"]["analytics_service"] is True

    @patch.object(vehicle_detector, 'is_ready', return_value=False)
    @patch.object(traffic_manager, 'is_ready', return_value=True)
    @patch.object(analytics_service, 'is_ready', return_value=True)
    def test_health_check_one_service_unhealthy(self, mock_analytics, mock_traffic, mock_vehicle, client):
        """Test health check when one service is unhealthy."""
        response = client.get("/api/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "error"
        assert data["services"]["vehicle_detector"] is False
        assert data["services"]["traffic_manager"] is True
        assert data["services"]["analytics_service"] is True

    def test_health_check_missing_services(self, client):
        """Test health check with missing services."""
        with patch('app.main.vehicle_detector', None):
            response = client.get("/api/health")
            assert response.status_code == 503

    @patch.object(vehicle_detector, 'is_ready', side_effect=Exception("Service error"))
    def test_health_check_services_not_ready(self, mock_vehicle, client):
        """Test health check with services not ready."""
        response = client.get("/api/health")
        assert response.status_code == 503
