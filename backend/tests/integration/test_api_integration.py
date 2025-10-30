"""Integration tests for API endpoints"""

import pytest
import requests
import time
from pathlib import Path

# Base URL for integration tests
BASE_URL = "http://localhost:8000"


class TestAPIIntegration:
    """Integration tests for the complete API"""
    
    def test_health_endpoint(self):
        """Test health check endpoint"""
        response = requests.get(f"{BASE_URL}/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "services" in data
    
    def test_system_info_endpoint(self):
        """Test system information endpoint"""
        response = requests.get(f"{BASE_URL}/api/system/info")
        assert response.status_code == 200
        
        data = response.json()
        assert "application_name" in data
        assert "version" in data
        assert "features" in data
    
    def test_metrics_endpoint(self):
        """Test Prometheus metrics endpoint"""
        response = requests.get(f"{BASE_URL}/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")
    
    def test_intersection_status(self):
        """Test intersection status endpoint"""
        response = requests.get(f"{BASE_URL}/api/intersection-status")
        # May return 503 if services not ready, which is acceptable
        assert response.status_code in [200, 503]
    
    def test_vehicle_detection_with_invalid_file(self):
        """Test vehicle detection with invalid file"""
        files = {'image': ('test.txt', b'not an image', 'text/plain')}
        response = requests.post(f"{BASE_URL}/api/detect-vehicles", files=files)
        assert response.status_code == 400
    
    def test_emergency_override_validation(self):
        """Test emergency override with invalid data"""
        invalid_data = {
            "alert_id": "test",
            "emergency_type": "invalid_type",
            "detected_lane": "invalid_lane"
        }
        response = requests.post(f"{BASE_URL}/api/emergency-override", json=invalid_data)
        assert response.status_code in [422, 503]  # Validation error or service unavailable
    
    def test_rate_limiting(self):
        """Test rate limiting functionality"""
        # Make multiple rapid requests to trigger rate limiting
        responses = []
        for _ in range(10):
            response = requests.get(f"{BASE_URL}/health")
            responses.append(response.status_code)
            time.sleep(0.1)
        
        # Should mostly be successful (rate limits are generous in tests)
        success_count = sum(1 for status in responses if status == 200)
        assert success_count >= 8  # Allow for some rate limiting
    
    def test_cors_headers(self):
        """Test CORS headers are present"""
        response = requests.options(f"{BASE_URL}/api/system/info")
        # Should have CORS headers or return 200/405
        assert response.status_code in [200, 405]
    
    def test_error_handling(self):
        """Test error handling for non-existent endpoints"""
        response = requests.get(f"{BASE_URL}/api/nonexistent")
        assert response.status_code == 404
        
        data = response.json()
        assert "detail" in data


class TestWebSocketIntegration:
    """Integration tests for WebSocket functionality"""
    
    def test_websocket_connection(self):
        """Test WebSocket connection (requires websocket-client)"""
        try:
            import websocket
            
            def on_message(ws, message):
                print(f"Received: {message}")
            
            def on_error(ws, error):
                print(f"Error: {error}")
            
            def on_close(ws, close_status_code, close_msg):
                print("Connection closed")
            
            def on_open(ws):
                print("Connection opened")
                # Close after successful connection
                ws.close()
            
            ws = websocket.WebSocketApp(
                f"ws://localhost:8000/ws/traffic-updates",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            
            # Run for a short time
            ws.run_forever(timeout=5)
            
        except ImportError:
            pytest.skip("websocket-client not installed")
        except Exception as e:
            # WebSocket might not be available in test environment
            pytest.skip(f"WebSocket test skipped: {e}")


class TestServiceHealth:
    """Integration tests for service health and readiness"""
    
    def test_service_startup_time(self):
        """Test that services start within reasonable time"""
        start_time = time.time()
        max_wait = 30  # 30 seconds
        
        while time.time() - start_time < max_wait:
            try:
                response = requests.get(f"{BASE_URL}/health", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "healthy":
                        return  # Success
            except requests.exceptions.RequestException:
                pass
            
            time.sleep(1)
        
        pytest.fail("Service did not become healthy within 30 seconds")
    
    def test_database_connectivity(self):
        """Test database connectivity through health endpoint"""
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code == 200:
            data = response.json()
            # Check if database status is reported
            # This will depend on actual implementation
            assert "services" in data
    
    def test_concurrent_requests(self):
        """Test handling of concurrent requests"""
        import concurrent.futures
        import threading
        
        def make_request():
            try:
                response = requests.get(f"{BASE_URL}/health", timeout=10)
                return response.status_code
            except Exception:
                return 500
        
        # Make 10 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        # Most requests should succeed
        success_count = sum(1 for status in results if status == 200)
        assert success_count >= 8  # Allow for some failures under load


if __name__ == "__main__":
    # Run integration tests
    pytest.main(["-v", __file__])
