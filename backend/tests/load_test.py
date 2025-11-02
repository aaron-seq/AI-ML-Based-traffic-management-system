"""
Load testing for AI Traffic Management System API
Tests system performance under concurrent load
"""

import random
import time
from io import BytesIO
from locust import HttpUser, task, between
from PIL import Image


class TrafficSystemUser(HttpUser):
    """Simulated user for load testing the traffic management system"""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Called when a user starts - setup any initial data"""
        self.test_image = self._create_test_image()
    
    def _create_test_image(self) -> BytesIO:
        """Create a test image for upload testing"""
        # Create a simple test image
        img = Image.new('RGB', (640, 480), color='blue')
        img_bytes = BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        return img_bytes
    
    @task(3)
    def health_check(self):
        """Test health endpoint - most frequent request"""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")
    
    @task(2)
    def system_info(self):
        """Test system info endpoint"""
        with self.client.get("/api/system/info", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"System info failed: {response.status_code}")
    
    @task(2)
    def intersection_status(self):
        """Test intersection status endpoint"""
        with self.client.get("/api/intersection-status", catch_response=True) as response:
            if response.status_code in [200, 503]:  # 503 if service not available
                response.success()
            else:
                response.failure(f"Intersection status failed: {response.status_code}")
    
    @task(1)
    def vehicle_detection(self):
        """Test vehicle detection endpoint - most resource intensive"""
        # Reset image bytes position
        self.test_image.seek(0)
        
        files = {'image': ('test_image.jpg', self.test_image, 'image/jpeg')}
        
        with self.client.post("/api/detect-vehicles", files=files, catch_response=True) as response:
            if response.status_code in [200, 503]:  # 503 if service not available
                response.success()
            elif response.status_code == 413:  # File too large
                response.success()  # Expected for some test cases
            else:
                response.failure(f"Vehicle detection failed: {response.status_code}")
    
    @task(1)
    def emergency_override(self):
        """Test emergency override endpoint"""
        emergency_data = {
            "alert_id": f"test_alert_{random.randint(1000, 9999)}",
            "emergency_type": random.choice(["ambulance", "fire_truck", "police"]),
            "detected_lane": random.choice(["north", "south", "east", "west"]),
            "priority_level": random.randint(1, 5)
        }
        
        with self.client.post("/api/emergency-override", json=emergency_data, catch_response=True) as response:
            if response.status_code in [200, 503]:  # 503 if service not available
                response.success()
            else:
                response.failure(f"Emergency override failed: {response.status_code}")
    
    @task(1)
    def analytics_summary(self):
        """Test analytics summary endpoint"""
        period = random.choice(["current", "hourly", "daily"])
        
        with self.client.get(f"/api/analytics/summary?period={period}", catch_response=True) as response:
            if response.status_code in [200, 503]:  # 503 if service not available
                response.success()
            else:
                response.failure(f"Analytics summary failed: {response.status_code}")
    
    @task(1)
    def metrics_endpoint(self):
        """Test Prometheus metrics endpoint"""
        with self.client.get("/metrics", catch_response=True) as response:
            if response.status_code == 200:
                # Verify it's Prometheus format
                if "# HELP" in response.text or "# TYPE" in response.text:
                    response.success()
                else:
                    response.failure("Metrics endpoint didn't return Prometheus format")
            else:
                response.failure(f"Metrics endpoint failed: {response.status_code}")


class HeavyLoadUser(HttpUser):
    """Heavy load user for stress testing"""
    
    wait_time = between(0.1, 0.5)  # More aggressive timing
    weight = 1  # Lower weight, fewer of these users
    
    def on_start(self):
        self.large_test_image = self._create_large_test_image()
    
    def _create_large_test_image(self) -> BytesIO:
        """Create a larger test image for stress testing"""
        img = Image.new('RGB', (1920, 1080), color='red')
        img_bytes = BytesIO()
        img.save(img_bytes, format='JPEG', quality=95)
        img_bytes.seek(0)
        return img_bytes
    
    @task(1)
    def stress_vehicle_detection(self):
        """Stress test vehicle detection with large images"""
        self.large_test_image.seek(0)
        
        files = {'image': ('large_test_image.jpg', self.large_test_image, 'image/jpeg')}
        
        with self.client.post("/api/detect-vehicles", files=files, catch_response=True) as response:
            if response.status_code in [200, 413, 503]:  # Various expected responses
                response.success()
            else:
                response.failure(f"Stress test failed: {response.status_code}")
    
    @task(2)
    def rapid_health_checks(self):
        """Rapid health checks to test rate limiting"""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code in [200, 429]:  # 429 = rate limited
                response.success()
            else:
                response.failure(f"Rapid health check failed: {response.status_code}")


class WebSocketUser(HttpUser):
    """User for testing WebSocket connections"""
    
    weight = 1  # Lower weight
    
    def on_start(self):
        """Setup WebSocket connection simulation"""
        # Note: Locust doesn't natively support WebSocket load testing
        # This is a placeholder for WebSocket testing logic
        # You would need to use a different tool like Artillery for WebSocket load testing
        pass
    
    @task(1)
    def simulate_websocket_load(self):
        """Simulate WebSocket load by making rapid requests"""
        # Simulate what a WebSocket connection might do
        endpoints = ["/api/intersection-status", "/health", "/api/system/info"]
        
        for endpoint in endpoints:
            with self.client.get(endpoint, catch_response=True) as response:
                if response.status_code in [200, 503]:
                    response.success()
                else:
                    response.failure(f"WebSocket simulation failed: {response.status_code}")
            time.sleep(0.1)  # Brief pause between requests


if __name__ == "__main__":
    # Run with: locust -f load_test.py --host=http://localhost:8000
    print("Load test ready. Run with: locust -f load_test.py --host=http://localhost:8000")
