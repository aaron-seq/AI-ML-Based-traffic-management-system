"""
Traffic Management System Data Models
Defines all data structures using Pydantic for validation and serialization
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field, field_validator


class TrafficSignalState(str, Enum):
    """Traffic signal states"""
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"


class LaneDirection(str, Enum):
    """Traffic lane directions"""
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"


class VehicleType(str, Enum):
    """Types of detected vehicles"""
    CAR = "car"
    TRUCK = "truck"
    BUS = "bus"
    MOTORCYCLE = "motorcycle"
    EMERGENCY = "emergency"


class EmergencyType(str, Enum):
    """Emergency vehicle types"""
    AMBULANCE = "ambulance"
    FIRE_TRUCK = "fire_truck"
    POLICE = "police"


class DetectedVehicle(BaseModel):
    """Represents a single detected vehicle"""
    
    vehicle_type: VehicleType
    confidence: float = Field(..., ge=0.0, le=1.0)
    bounding_box: Dict[str, int]
    lane: LaneDirection
    
    @field_validator('bounding_box')
    def validate_bounding_box(cls, value):
        if not all(k in value for k in ['x1', 'y1', 'x2', 'y2']):
            raise ValueError("Bounding box must contain x1, y1, x2, y2")
        if value['x2'] <= value['x1'] or value['y2'] <= value['y1']:
            raise ValueError("Invalid bounding box coordinates")
        return value


class VehicleDetectionResult(BaseModel):
    """Result of vehicle detection analysis"""
    
    total_vehicles: int
    lane_counts: Dict[LaneDirection, int]
    detected_vehicles: List[DetectedVehicle]
    image_path: Optional[str]
    annotated_image_path: Optional[str] = None
    processing_time: float
    confidence_scores: List[float]


class TrafficSignal(BaseModel):
    """Represents a traffic signal's state"""
    
    direction: LaneDirection
    state: TrafficSignalState
    remaining_time: int


class IntersectionStatus(BaseModel):
    """Complete status of a traffic intersection"""
    
    signals: Dict[LaneDirection, TrafficSignal]
    vehicle_counts: Dict[LaneDirection, int]
    emergency_mode_active: bool = False
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class EmergencyAlert(BaseModel):
    """Emergency vehicle alert information"""
    
    alert_id: str
    emergency_type: EmergencyType
    detected_lane: LaneDirection


class SystemHealthStatus(BaseModel):
    """Represents the health status of the system."""
    
    status: str
    uptime: float
    cpu_usage: float
    memory_usage: float
    services: Dict[str, bool]
