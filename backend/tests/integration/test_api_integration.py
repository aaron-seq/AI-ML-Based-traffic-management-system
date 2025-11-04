"""Integration tests for API endpoints"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

from app.main import app

@pytest.fixture(scope="module")
def client():
    """Provides a TestClient instance for the API tests."""
    with patch('app.main.vehicle_detector', new_callable=AsyncMock) as mock_detector:
        with TestClient(app) as c:
            yield c

class TestAPIIntegration:
    """Integration tests for the complete API."""

    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "uptime" in data

    @patch('app.main.settings')
    def test_system_info_endpoint(self, mock_settings, client):
        """Test system information endpoint."""
        mock_settings.application_name = "Test App"
        mock_settings.application_version = "1.0.0"

        response = client.get("/api/system/info")
        assert response.status_code == 200
        data = response.json()
        assert data["application_name"] == "AI Traffic Management System"
        assert data["version"] == "2.0.0"

    def test_metrics_endpoint(self, client):
        """Test Prometheus metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")

    @patch('app.main.traffic_manager')
    def test_intersection_status(self, mock_manager, client):
        """Test intersection status endpoint."""
        mock_manager.is_ready.return_value = True
        mock_manager.get_current_status.return_value = MagicMock(
            signals={}, vehicle_counts={}, emergency_mode_active=False
        )
        response = client.get("/api/intersection-status")
        assert response.status_code == 200

    def test_vehicle_detection_with_invalid_file(self, client):
        """Test vehicle detection with an invalid file type."""
        files = {'image': ('test.txt', b'not an image', 'text/plain')}
        response = client.post("/api/detect-vehicles", files=files)
        assert response.status_code == 400

    def test_emergency_override_validation(self, client):
        """Test emergency override with invalid data."""
        invalid_data = {"alert_id": "test", "emergency_type": "invalid", "detected_lane": "north"}
        response = client.post("/api/emergency-override", json=invalid_data)
        assert response.status_code == 422

    def test_error_handling(self, client):
        """Test error handling for non-existent endpoints."""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
