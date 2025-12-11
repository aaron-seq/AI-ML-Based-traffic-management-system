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
    FLASHING_RED = "flashing_red"
    FLASHING_YELLOW = "flashing_yellow"


class LaneDirection(str, Enum):
    """Traffic lane directions"""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    UNKNOWN = "unknown"


class VehicleType(str, Enum):
    """Types of detected vehicles"""

    CAR = "car"
    TRUCK = "truck"
    BUS = "bus"
    MOTORCYCLE = "motorcycle"
    BICYCLE = "bicycle"
    EMERGENCY = "emergency"
    PEDESTRIAN = "pedestrian"


class EmergencyType(str, Enum):
    """Emergency vehicle types"""

    AMBULANCE = "ambulance"
    FIRE_TRUCK = "fire_truck"
    POLICE = "police"
    RESCUE = "rescue"
    OTHER = "other"


class DetectedVehicle(BaseModel):
    """Represents a single detected vehicle"""

    vehicle_type: VehicleType
    confidence: float = Field(..., ge=0.0, le=1.0)
    bounding_box: Dict[str, int] = Field(
        ..., description="Bounding box coordinates {x1, y1, x2, y2}"
    )
    center_coordinates: Dict[str, float] = Field(
        ..., description="Normalized center coordinates {x, y}"
    )
    lane: LaneDirection
    is_emergency: bool = False
    vehicle_id: Optional[str] = None
    detection_timestamp: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("bounding_box")
    def validate_bounding_box(cls, value):
        required_keys = {"x1", "y1", "x2", "y2"}
        if not required_keys.issubset(value.keys()):
            raise ValueError(f"Bounding box must contain keys: {required_keys}")
        if value["x2"] <= value["x1"] or value["y2"] <= value["y1"]:
            raise ValueError("Invalid bounding box coordinates")
        return value

    @field_validator("center_coordinates")
    def validate_center_coordinates(cls, value):
        required_keys = {"x", "y"}
        if not required_keys.issubset(value.keys()):
            raise ValueError(f"Center coordinates must contain keys: {required_keys}")
        if not (0 <= value["x"] <= 1 and 0 <= value["y"] <= 1):
            raise ValueError("Center coordinates must be normalized (0-1)")
        return value


class VehicleDetectionResult(BaseModel):
    """Result of vehicle detection analysis"""

    total_vehicles: int = Field(..., ge=0)
    lane_counts: Dict[LaneDirection, int] = Field(default_factory=dict)
    detected_vehicles: List[DetectedVehicle] = Field(default_factory=list)
    confidence_scores: List[float] = Field(default_factory=list)
    processing_time: float = Field(..., gt=0)
    image_path: str
    annotated_image_path: Optional[str] = None
    has_emergency_vehicles: bool = False
    traffic_density: float = Field(default=0.0, ge=0.0)
    detection_timestamp: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("lane_counts")
    def validate_lane_counts(cls, value):
        # Ensure all lane directions are represented
        for lane in LaneDirection:
            if lane not in value:
                value[lane] = 0
        return value


class TrafficSignal(BaseModel):
    """Represents a traffic signal state and timing"""

    signal_id: str
    direction: LaneDirection
    current_state: TrafficSignalState
    remaining_time: int = Field(..., ge=0, description="Remaining time in seconds")
    next_state: Optional[TrafficSignalState] = None
    cycle_duration: int = Field(
        default=60, gt=0, description="Total cycle duration in seconds"
    )
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    def is_active(self) -> bool:
        """Check if signal allows traffic flow"""
        return self.current_state == TrafficSignalState.GREEN


class IntersectionStatus(BaseModel):
    """Complete status of traffic intersection"""

    intersection_id: str = Field(default="main_intersection")
    traffic_signals: Dict[LaneDirection, TrafficSignal] = Field(default_factory=dict)
    vehicle_counts: Dict[LaneDirection, int] = Field(default_factory=dict)
    total_vehicles: int = 0
    traffic_flow_rate: float = Field(default=0.0, ge=0.0)
    average_wait_time: float = Field(default=0.0, ge=0.0)
    emergency_mode_active: bool = False
    system_status: str = Field(default="operational")
    last_detection_time: Optional[datetime] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class EmergencyAlert(BaseModel):
    """Emergency vehicle alert information"""

    alert_id: str
    emergency_type: EmergencyType
    detected_lane: LaneDirection
    vehicle_location: Dict[str, float] = Field(..., description="Vehicle coordinates")
    priority_level: int = Field(..., ge=1, le=5, description="Priority level 1-5")
    estimated_arrival_time: Optional[int] = Field(None, description="ETA in seconds")
    override_duration: int = Field(
        default=60, gt=0, description="Override duration in seconds"
    )
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class TrafficSnapshot(BaseModel):
    """Snapshot of traffic system state at a point in time"""

    snapshot_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    intersection_status: IntersectionStatus
    vehicle_detection_result: Optional[VehicleDetectionResult] = None
    active_emergency_alerts: List[EmergencyAlert] = Field(default_factory=list)
    performance_metrics: Dict[str, Any] = Field(default_factory=dict)
    system_health: Dict[str, bool] = Field(default_factory=dict)
