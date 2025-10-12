"""
Intelligent Vehicle Detection Service using YOLOv8
Handles real-time vehicle detection and traffic analysis
"""

import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from ultralytics import YOLO
from PIL import Image, ImageDraw, ImageFont

from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import VehicleDetectionResult, DetectedVehicle


class IntelligentVehicleDetector(LoggerMixin):
    """Modern vehicle detection service using YOLOv8"""
    
    # Vehicle class mapping for COCO dataset
    VEHICLE_CLASSES = {
        2: 'car',
        3: 'motorcycle', 
        5: 'bus',
        7: 'truck'
    }
    
    # Lane detection zones (normalized coordinates)
    LANE_ZONES = {
        'north': {'x_min': 0.45, 'x_max': 0.55, 'y_min': 0.0, 'y_max': 0.45},
        'south': {'x_min': 0.45, 'x_max': 0.55, 'y_min': 0.55, 'y_max': 1.0},
        'east': {'x_min': 0.55, 'x_max': 1.0, 'y_min': 0.45, 'y_max': 0.55},
        'west': {'x_min': 0.0, 'x_max': 0.45, 'y_min': 0.45, 'y_max': 0.55}
    }
    
    def __init__(self):
        super().__init__()
        self.model: Optional[YOLO] = None
        self.model_initialized = False
        self.performance_metrics = {
            'total_detections': 0,
            'average_inference_time': 0.0,
            'last_detection_time': None
        }
    
    async def initialize(self) -> None:
        """Initialize the YOLOv8 model asynchronously"""
        try:
            start_time = time.time()
            self.logger.info("Initializing YOLOv8 model...")
            
            # Create model directory if it doesn't exist
            model_path = Path(settings.model_cache_directory)
            model_path.mkdir(parents=True, exist_ok=True)
            
            # Initialize model in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(
                None, 
                self._load_model
            )
            
            initialization_time = time.time() - start_time
            self.model_initialized = True
            
            self.log_performance(
                "model_initialization", 
                initialization_time
            )
            self.logger.info(f"YOLOv8 model initialized successfully")
            
        except Exception as error:
            self.log_error_with_context(error, "model_initialization")
            raise
    
    def _load_model(self) -> YOLO:
        """Load YOLOv8 model (runs in thread pool)"""
        model_file = Path(settings.model_cache_directory) / settings.model_name
        
        if model_file.exists():
            self.logger.info(f"Loading cached model from {model_file}")
            return YOLO(str(model_file))
        else:
            self.logger.info(f"Downloading {settings.model_name} model...")
            return YOLO(settings.model_name)
    
    async def analyze_intersection_image(
        self, 
        image_path: str,
        save_annotated: bool = True
    ) -> VehicleDetectionResult:
        """Analyze intersection image for vehicle detection"""
        if not self.model_initialized:
            await self.initialize()
        
        try:
            start_time = time.time()
            
            # Load and process image
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Could not load image from {image_path}")
            
            # Run detection
            results = await self._run_detection(image)
            
            # Process results
            detected_vehicles = self._process_detection_results(results, image.shape)
            lane_counts = self._count_vehicles_by_lane(detected_vehicles)
            
            # Save annotated image if requested
            annotated_image_path = None
            if save_annotated:
                annotated_image_path = await self._save_annotated_image(
                    image, detected_vehicles, image_path
                )
            
            # Update performance metrics
            inference_time = time.time() - start_time
            self._update_performance_metrics(inference_time)
            
            result = VehicleDetectionResult(
                total_vehicles=len(detected_vehicles),
                lane_counts=lane_counts,
                detected_vehicles=detected_vehicles,
                confidence_scores=[v.confidence for v in detected_vehicles],
                processing_time=inference_time,
                image_path=image_path,
                annotated_image_path=annotated_image_path
            )
            
            self.log_performance("vehicle_detection", inference_time)
            self.logger.info(
                f"Detected {len(detected_vehicles)} vehicles in {inference_time:.3f}s"
            )
            
            return result
            
        except Exception as error:
            self.log_error_with_context(error, "vehicle_detection")
            raise
    
    async def _run_detection(self, image: np.ndarray) -> List:
        """Run YOLOv8 detection on image"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.model(
                image,
                conf=settings.detection_confidence_threshold,
                iou=settings.non_max_suppression_threshold,
                device='cuda' if settings.enable_gpu_acceleration else 'cpu'
            )
        )
    
    def _process_detection_results(
        self, 
        results: List, 
        image_shape: Tuple[int, int, int]
    ) -> List[DetectedVehicle]:
        """Process YOLOv8 detection results into DetectedVehicle objects"""
        detected_vehicles = []
        height, width = image_shape[:2]
        
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
                
            for box in boxes:
                # Get class ID and confidence
                class_id = int(box.cls.item())
                confidence = float(box.conf.item())
                
                # Only process vehicle classes
                if class_id not in self.VEHICLE_CLASSES:
                    continue
                
                # Get bounding box coordinates
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                
                # Normalize coordinates
                center_x = ((x1 + x2) / 2) / width
                center_y = ((y1 + y2) / 2) / height
                
                # Determine lane
                lane = self._determine_vehicle_lane(center_x, center_y)
                
                vehicle = DetectedVehicle(
                    vehicle_type=self.VEHICLE_CLASSES[class_id],
                    confidence=confidence,
                    bounding_box={
                        'x1': int(x1), 'y1': int(y1),
                        'x2': int(x2), 'y2': int(y2)
                    },
                    center_coordinates={'x': center_x, 'y': center_y},
                    lane=lane
                )
                
                detected_vehicles.append(vehicle)
        
        return detected_vehicles
    
    def _determine_vehicle_lane(self, center_x: float, center_y: float) -> str:
        """Determine which lane a vehicle belongs to based on position"""
        for lane, zone in self.LANE_ZONES.items():
            if (zone['x_min'] <= center_x <= zone['x_max'] and 
                zone['y_min'] <= center_y <= zone['y_max']):
                return lane
        return 'unknown'
    
    def _count_vehicles_by_lane(self, vehicles: List[DetectedVehicle]) -> Dict[str, int]:
        """Count vehicles in each lane"""
        lane_counts = {'north': 0, 'south': 0, 'east': 0, 'west': 0}
        
        for vehicle in vehicles:
            if vehicle.lane in lane_counts:
                lane_counts[vehicle.lane] += 1
        
        return lane_counts
    
    async def _save_annotated_image(
        self, 
        image: np.ndarray, 
        vehicles: List[DetectedVehicle], 
        original_path: str
    ) -> str:
        """Save image with vehicle detection annotations"""
        try:
            # Convert to PIL for better text rendering
            pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil_image)
            
            # Try to load a font, fall back to default if not available
            try:
                font = ImageFont.truetype("arial.ttf", 16)
            except OSError:
                font = ImageFont.load_default()
            
            # Color mapping for vehicle types
            colors = {
                'car': 'red',
                'truck': 'blue', 
                'bus': 'green',
                'motorcycle': 'orange'
            }
            
            for vehicle in vehicles:
                bbox = vehicle.bounding_box
                color = colors.get(vehicle.vehicle_type, 'yellow')
                
                # Draw bounding box
                draw.rectangle(
                    [(bbox['x1'], bbox['y1']), (bbox['x2'], bbox['y2'])],
                    outline=color,
                    width=2
                )
                
                # Draw label
                label = f"{vehicle.vehicle_type} ({vehicle.confidence:.2f})"
                draw.text(
                    (bbox['x1'], bbox['y1'] - 20),
                    label,
                    fill=color,
                    font=font
                )
            
            # Save annotated image
            output_dir = Path("./output_images")
            output_dir.mkdir(exist_ok=True)
            
            original_name = Path(original_path).stem
            output_path = output_dir / f"{original_name}_annotated.jpg"
            
            # Convert back to BGR for OpenCV
            annotated_cv2 = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(output_path), annotated_cv2)
            
            return str(output_path)
            
        except Exception as error:
            self.log_error_with_context(error, "save_annotated_image")
            return None
    
    def _update_performance_metrics(self, inference_time: float) -> None:
        """Update performance metrics"""
        self.performance_metrics['total_detections'] += 1
        self.performance_metrics['last_detection_time'] = time.time()
        
        # Calculate rolling average
        current_avg = self.performance_metrics['average_inference_time']
        total_detections = self.performance_metrics['total_detections']
        
        self.performance_metrics['average_inference_time'] = (
            (current_avg * (total_detections - 1) + inference_time) / total_detections
        )
    
    def is_ready(self) -> bool:
        """Check if detector is ready for inference"""
        return self.model_initialized and self.model is not None
    
    def get_performance_metrics(self) -> Dict:
        """Get current performance metrics"""
        return self.performance_metrics.copy()
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        self.logger.info("Cleaning up vehicle detector resources")
        self.model = None
        self.model_initialized = False