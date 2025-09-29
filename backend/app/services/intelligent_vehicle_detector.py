"""
Intelligent Vehicle Detector using YOLOv8
Modern, efficient vehicle detection with enhanced capabilities
"""

import asyncio
import cv2
import numpy as np
from ultralytics import YOLO
from typing import Dict, List, Tuple, Optional
import torch
from pathlib import Path
import logging
from dataclasses import dataclass
from enum import Enum

from app.models.traffic_models import VehicleDetectionResult, DetectedVehicle, LaneDirection

logger = logging.getLogger(__name__)

class VehicleType(Enum):
    """Enhanced vehicle type classification"""
    CAR = "car"
    TRUCK = "truck" 
    BUS = "bus"
    MOTORCYCLE = "motorcycle"
    BICYCLE = "bicycle"
    EMERGENCY = "emergency"  # Emergency vehicles
    PEDESTRIAN = "pedestrian"

@dataclass
class DetectionConfig:
    """Configuration for vehicle detection"""
    model_size: str = "yolov8n.pt"  # nano, small, medium, large, xlarge
    confidence_threshold: float = 0.4
    nms_threshold: float = 0.45
    image_size: int = 640
    enable_gpu: bool = True
    emergency_detection: bool = True
    pedestrian_detection: bool = True

class IntelligentVehicleDetector:
    """
    Advanced vehicle detection system using YOLOv8
    Features:
    - Real-time detection with GPU acceleration
    - Emergency vehicle identification
    - Pedestrian detection
    - Lane-based vehicle counting
    - Performance optimization with caching
    """
    
    def __init__(self, config: DetectionConfig = None):
        self.config = config or DetectionConfig()
        self.model: Optional[YOLO] = None
        self.device = "cuda" if torch.cuda.is_available() and self.config.enable_gpu else "cpu"
        self.is_initialized = False
        
        # Vehicle class IDs from COCO dataset
        self.vehicle_classes = {
            2: VehicleType.CAR,      # car
            5: VehicleType.BUS,      # bus  
            7: VehicleType.TRUCK,    # truck
            3: VehicleType.MOTORCYCLE, # motorcycle
            1: VehicleType.BICYCLE,  # bicycle
            0: VehicleType.PEDESTRIAN # person (for pedestrian detection)
        }
        
        # Emergency vehicle detection keywords (for enhanced detection)
        self.emergency_indicators = [
            "ambulance", "police", "fire", "emergency", 
            "rescue", "patrol", "sheriff"
        ]
        
    async def initialize(self):
        """Initialize the YOLO model asynchronously"""
        try:
            logger.info(f"🤖 Loading YOLOv8 model: {self.config.model_size}")
            
            # Load model in a separate thread to avoid blocking
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(
                None, 
                lambda: YOLO(self.config.model_size)
            )
            
            # Move model to appropriate device
            if self.device == "cuda":
                self.model.to("cuda")
                logger.info("🚀 GPU acceleration enabled")
            else:
                logger.info("💻 Using CPU for inference")
            
            self.is_initialized = True
            logger.info("✅ Vehicle detector initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize vehicle detector: {e}")
            raise
    
    def is_ready(self) -> bool:
        """Check if detector is ready for use"""
        return self.is_initialized and self.model is not None
    
    async def analyze_intersection_image(self, image_path: str) -> VehicleDetectionResult:
        """
        Analyze intersection image and detect vehicles with lane assignment
        
        Args:
            image_path: Path to the intersection image
            
        Returns:
            VehicleDetectionResult with detected vehicles and lane counts
        """
        if not self.is_ready():
            raise RuntimeError("Vehicle detector not initialized")
        
        try:
            # Load and preprocess image
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Could not load image from {image_path}")
            
            original_height, original_width = image.shape[:2]
            
            # Run inference
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.model(
                    image,
                    conf=self.config.confidence_threshold,
                    iou=self.config.nms_threshold,
                    imgsz=self.config.image_size
                )
            )
            
            # Process detections
            detected_vehicles = []
            lane_counts = {lane.value: 0 for lane in LaneDirection}
            
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        # Extract detection data
                        class_id = int(box.cls[0])
                        confidence = float(box.conf[0])
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        
                        # Filter for vehicle classes
                        if class_id in self.vehicle_classes:
                            vehicle_type = self.vehicle_classes[class_id]
                            
                            # Check for emergency vehicle (enhanced detection)
                            if self._is_emergency_vehicle(image, x1, y1, x2, y2):
                                vehicle_type = VehicleType.EMERGENCY
                            
                            # Determine lane assignment
                            center_x = (x1 + x2) / 2
                            center_y = (y1 + y2) / 2
                            lane = self._assign_vehicle_to_lane(
                                center_x, center_y, original_width, original_height
                            )
                            
                            # Create detected vehicle object
                            vehicle = DetectedVehicle(
                                vehicle_type=vehicle_type.value,
                                confidence=confidence,
                                bounding_box=(x1, y1, x2, y2),
                                center_point=(center_x, center_y),
                                lane=lane.value,
                                is_emergency=(vehicle_type == VehicleType.EMERGENCY)
                            )
                            
                            detected_vehicles.append(vehicle)
                            lane_counts[lane.value] += 1
            
            # Calculate traffic density metrics
            total_vehicles = sum(lane_counts.values())
            traffic_density = self._calculate_traffic_density(lane_counts, original_width * original_height)
            
            # Detect emergency situations
            has_emergency = any(v.is_emergency for v in detected_vehicles)
            
            result = VehicleDetectionResult(
                lane_counts=lane_counts,
                total_vehicles=total_vehicles,
                detected_vehicles=detected_vehicles,
                traffic_density=traffic_density,
                has_emergency_vehicle=has_emergency,
                detection_confidence=self._calculate_average_confidence(detected_vehicles),
                timestamp=asyncio.get_event_loop().time()
            )
            
            logger.info(f"🚗 Detected {total_vehicles} vehicles across {len([c for c in lane_counts.values() if c > 0])} lanes")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Vehicle detection failed: {e}")
            raise
    
    def _assign_vehicle_to_lane(
        self, 
        center_x: float, 
        center_y: float, 
        image_width: int, 
        image_height: int
    ) -> LaneDirection:
        """
        Assign vehicle to traffic lane based on position in image
        Uses intelligent quadrant-based assignment with buffer zones
        """
        # Define quadrants with buffer zones to avoid edge cases
        mid_x = image_width / 2
        mid_y = image_height / 2
        buffer = 0.1  # 10% buffer zone
        
        buffer_x = image_width * buffer
        buffer_y = image_height * buffer
        
        # Enhanced lane assignment logic
        if center_x > mid_x + buffer_x:
            if center_y < mid_y - buffer_y:
                return LaneDirection.RIGHT
            else:
                return LaneDirection.DOWN
        else:
            if center_y > mid_y + buffer_y:
                return LaneDirection.LEFT
            else:
                return LaneDirection.UP
    
    def _is_emergency_vehicle(
        self, 
        image: np.ndarray, 
        x1: float, 
        y1: float, 
        x2: float, 
        y2: float
    ) -> bool:
        """
        Enhanced emergency vehicle detection using color analysis and patterns
        """
        try:
            # Extract vehicle region
            vehicle_roi = image[int(y1):int(y2), int(x1):int(x2)]
            
            if vehicle_roi.size == 0:
                return False
            
            # Convert to HSV for better color detection
            hsv = cv2.cvtColor(vehicle_roi, cv2.COLOR_BGR2HSV)
            
            # Define color ranges for emergency vehicles
            # Red range (fire trucks, ambulances)
            red_lower1 = np.array([0, 50, 50])
            red_upper1 = np.array([10, 255, 255])
            red_lower2 = np.array([170, 50, 50]) 
            red_upper2 = np.array([180, 255, 255])
            
            # Blue range (police vehicles)
            blue_lower = np.array([100, 50, 50])
            blue_upper = np.array([130, 255, 255])
            
            # Yellow range (some emergency vehicles)
            yellow_lower = np.array([20, 50, 50])
            yellow_upper = np.array([30, 255, 255])
            
            # Create masks
            red_mask1 = cv2.inRange(hsv, red_lower1, red_upper1)
            red_mask2 = cv2.inRange(hsv, red_lower2, red_upper2)
            blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)
            yellow_mask = cv2.inRange(hsv, yellow_lower, yellow_upper)
            
            # Combine masks
            emergency_mask = red_mask1 + red_mask2 + blue_mask + yellow_mask
            
            # Calculate percentage of emergency colors
            emergency_percentage = np.sum(emergency_mask > 0) / emergency_mask.size
            
            # Threshold for emergency vehicle detection
            return emergency_percentage > 0.15  # 15% of vehicle area
            
        except Exception as e:
            logger.warning(f"Emergency vehicle detection failed: {e}")
            return False
    
    def _calculate_traffic_density(self, lane_counts: Dict[str, int], image_area: int) -> float:
        """Calculate traffic density metric"""
        total_vehicles = sum(lane_counts.values())
        # Normalize by image area (vehicles per square pixel * 1000000)
        return (total_vehicles / image_area) * 1000000 if image_area > 0 else 0.0
    
    def _calculate_average_confidence(self, detected_vehicles: List[DetectedVehicle]) -> float:
        """Calculate average detection confidence"""
        if not detected_vehicles:
            return 0.0
        return sum(v.confidence for v in detected_vehicles) / len(detected_vehicles)

    async def detect_real_time_stream(self, video_source: str = 0):
        """
        Real-time detection from video stream (for future implementation)
        """
        # TODO: Implement real-time video stream processing
        pass
