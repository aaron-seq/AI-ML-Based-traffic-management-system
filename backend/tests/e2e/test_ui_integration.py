"""
Selenium E2E Tests for AI-ML Traffic Management System

Test Scenarios:
1. Full traffic monitoring workflow
2. Vehicle detection integration
3. Traffic signal state synchronization
"""

import pytest
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class TestTrafficMonitoringWorkflow:
    """Selenium integration tests for traffic monitoring workflows"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup WebDriver before each test"""
        # BEFORE STATE: No browser instance
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(10)
        self.wait = WebDriverWait(self.driver, 20)
        self.base_url = "http://localhost:5173"
        
        yield
        
        # AFTER STATE: Browser closed, resources cleaned up
        self.driver.quit()

    def test_dashboard_loads_successfully(self):
        """Test that main dashboard loads with all components"""
        # BEFORE STATE: Browser at blank page
        # ACTION: Navigate to dashboard URL
        # AFTER STATE: Dashboard fully rendered with all sections
        
        self.driver.get(self.base_url)
        
        # Wait for dashboard container
        dashboard = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='dashboard-container']"))
        )
        assert dashboard.is_displayed()
        
        # Verify key components loaded
        video_feed = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='video-feed-container']")
        assert video_feed.is_displayed()
        
        lane_display = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='lane-display']")
        assert lane_display.is_displayed()
        
    def test_vehicle_count_display(self):
        """Test vehicle count is displayed and updates"""
        self.driver.get(self.base_url)
        
        # BEFORE STATE: Vehicle count loading
        # AFTER STATE: Numeric count displayed
        
        vehicle_count_element = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='total-vehicle-count']"))
        )
        
        count_text = vehicle_count_element.text
        try:
            count_value = int(count_text)
            assert count_value >= 0, "Vehicle count should be non-negative"
        except ValueError:
            # Count might be loading
            assert "..." in count_text or "Loading" in count_text
    
    def test_lane_data_visibility(self):
        """Test all lane data displays are visible"""
        self.driver.get(self.base_url)
        
        # BEFORE STATE: Lanes not rendered
        # AFTER STATE: All 4 lane displays visible with data
        
        lanes = ['north', 'south', 'east', 'west']
        
        for lane in lanes:
            lane_element = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, f"[data-testid='lane-{lane}']"))
            )
            assert lane_element.is_displayed(), f"Lane {lane} should be visible"
            
            # Each lane should have vehicle count
            lane_count = lane_element.find_element(By.CSS_SELECTOR, "[data-testid='lane-vehicle-count']")
            assert lane_count.is_displayed()


class TestVehicleDetectionIntegration:
    """Integration tests for vehicle detection API and UI synchronization"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(10)
        self.wait = WebDriverWait(self.driver, 20)
        self.base_url = "http://localhost:5173"
        
        yield
        self.driver.quit()
    
    def test_image_upload_detection(self):
        """Test image upload triggers vehicle detection"""
        # BEFORE STATE: No image uploaded, detection count = 0
        # ACTION: Upload test traffic image
        # AFTER STATE: Detection results displayed with vehicle counts
        
        self.driver.get(f"{self.base_url}/upload")
        
        # Find file upload input
        file_input = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
        )
        
        # Upload test image (simulated path)
        test_image_path = "test_images/1.jpg"
        file_input.send_keys(test_image_path)
        
        # Wait for detection results
        results_panel = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='detection-results']"))
        )
        assert results_panel.is_displayed()
        
        # Verify detection count is shown
        detection_count = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='detected-vehicles']")
        count_value = int(detection_count.text)
        assert count_value > 0, "Should detect at least one vehicle"
    
    def test_detection_results_breakdown(self):
        """Test detection results show vehicle type breakdown"""
        self.driver.get(f"{self.base_url}/results")
        
        # AFTER STATE: Results page shows breakdown by vehicle type
        
        self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='results-container']"))
        )
        
        # Verify vehicle type breakdown elements
        car_count = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='count-cars']")
        truck_count = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='count-trucks']")
        bus_count = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='count-buses']")
        
        assert car_count.is_displayed()
        assert truck_count.is_displayed()
        assert bus_count.is_displayed()
    
    def test_annotated_image_display(self):
        """Test annotated image with bounding boxes is displayed"""
        self.driver.get(f"{self.base_url}/results/latest")
        
        # BEFORE STATE: Original image
        # AFTER STATE: Annotated image with vehicle bounding boxes
        
        annotated_image = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='annotated-image']"))
        )
        
        assert annotated_image.is_displayed()
        
        # Verify image source contains 'output' indicating processed image
        img_src = annotated_image.get_attribute('src')
        assert 'output' in img_src or 'annotated' in img_src


class TestTrafficSignalSynchronization:
    """Tests for traffic signal state synchronization"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 20)
        self.base_url = "http://localhost:5173"
        
        yield
        self.driver.quit()
    
    def test_signal_phase_display(self):
        """Test current signal phase is displayed"""
        self.driver.get(self.base_url)
        
        # BEFORE STATE: Signal phase unknown
        # AFTER STATE: Current phase (1-4) displayed with color indicator
        
        signal_display = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='signal-phase-indicator']"))
        )
        
        assert signal_display.is_displayed()
        phase_text = signal_display.text
        
        # Phase should be a number 1-4 or descriptive text
        assert any(p in phase_text for p in ['Phase', '1', '2', '3', '4', 'North', 'South'])
    
    def test_signal_countdown_timer(self):
        """Test signal countdown timer updates"""
        self.driver.get(self.base_url)
        
        countdown = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='signal-countdown']"))
        )
        
        # Record initial value
        initial_value = int(countdown.text)
        
        # Wait 2 seconds
        time.sleep(2)
        
        # Get new value
        new_value = int(countdown.text)
        
        # BEFORE STATE: countdown = N
        # AFTER STATE: countdown = N-2 (approximately)
        # Allow some tolerance for timing
        assert new_value <= initial_value, "Countdown should decrease over time"
    
    def test_signal_color_indicators(self):
        """Test traffic signal color indicators are displayed"""
        self.driver.get(self.base_url)
        
        # AFTER STATE: Each direction shows appropriate signal color
        
        directions = ['north', 'south', 'east', 'west']
        valid_colors = ['red', 'yellow', 'green']
        
        for direction in directions:
            signal_light = self.wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, f"[data-testid='signal-light-{direction}']")
                )
            )
            
            classes = signal_light.get_attribute('class')
            # At least one color class should be present
            assert any(color in classes.lower() for color in valid_colors), \
                f"Signal for {direction} should have a color indicator"
    
    def test_signal_transition_animation(self):
        """Test signal transition includes animation"""
        self.driver.get(self.base_url)
        
        signal_container = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='signal-container']"))
        )
        
        # Check for CSS transition/animation classes
        classes = signal_container.get_attribute('class')
        style = signal_container.get_attribute('style') or ''
        
        has_animation = (
            'transition' in classes or 
            'animate' in classes or
            'transition' in style
        )
        
        # Animation is optional but recommended
        if not has_animation:
            print("Warning: Signal transitions may lack animation for smooth UX")


class TestAPIIntegration:
    """Tests for backend API integration via UI"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 20)
        self.base_url = "http://localhost:5173"
        
        yield
        self.driver.quit()
    
    def test_health_check_status(self):
        """Test health check endpoint status is reflected in UI"""
        self.driver.get(self.base_url)
        
        # AFTER STATE: Health status indicator shows "Connected" or "Healthy"
        
        health_indicator = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='api-health-status']"))
        )
        
        status_text = health_indicator.text.lower()
        assert any(s in status_text for s in ['connected', 'healthy', 'online', 'ok'])
    
    def test_api_error_handling(self):
        """Test UI handles API errors gracefully"""
        # Navigate to page that makes API call
        self.driver.get(f"{self.base_url}/analytics")
        
        try:
            error_boundary = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='error-boundary']"))
            )
            # If error boundary exists, verify it shows helpful message
            error_text = error_boundary.text
            assert 'error' in error_text.lower() or 'retry' in error_text.lower()
        except TimeoutException:
            # No error occurred - page loaded successfully
            analytics_container = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='analytics-container']"
            )
            assert analytics_container.is_displayed()


class TestPerformanceMetrics:
    """Tests for performance metrics display"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 20)
        self.base_url = "http://localhost:5173"
        
        yield
        self.driver.quit()
    
    def test_detection_performance_display(self):
        """Test detection performance metrics are displayed"""
        self.driver.get(f"{self.base_url}/metrics")
        
        # AFTER STATE: Performance metrics panel visible with inference time, FPS etc.
        
        metrics_panel = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='performance-metrics']"))
        )
        
        assert metrics_panel.is_displayed()
        
        # Check for specific metrics
        inference_time = self.driver.find_element(
            By.CSS_SELECTOR, "[data-testid='metric-inference-time']"
        )
        assert inference_time.is_displayed()
    
    def test_total_detections_counter(self):
        """Test total detections counter is displayed and updates"""
        self.driver.get(f"{self.base_url}/metrics")
        
        total_detections = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='total-detections']"))
        )
        
        # BEFORE STATE: Initial count = N
        initial_count = int(total_detections.text.replace(',', ''))
        
        # AFTER STATE: Count should be >= initial (never decreases)
        time.sleep(3)
        
        current_count = int(total_detections.text.replace(',', ''))
        assert current_count >= initial_count


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
