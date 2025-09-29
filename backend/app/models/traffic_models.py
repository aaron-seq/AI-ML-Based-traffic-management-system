"""
Data models for the AI Traffic Management System
Using Pydantic for validation and serialization
"""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime

class LaneDirection(Enum):
    """Traffic lane directions"""
    RIGHT = "right"
    LEFT = "left" 
    UP = "up"
    DOWN = "down"

class SignalState(Enum):
    """Traffic signal states"""
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    FLASHING_RED = "flashing_red"
    FLASHING_YELLOW = "flashing_yellow"

class EmergencyType(Enum):
    """Emergency vehicle types"""
    AMBULANCE = "ambulance"
    FIRE_TRUCK = "fire_truck"
    POLICE = "police"
    RESCUE = "rescue"

class DetectedVehicle(BaseModel):
    """Individual detected vehicle"""
    vehicle_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    bounding_box: Tuple[float, float, float, float]
    center_point: Tuple[float, float]
    lane: str
    is_emergency: bool = False
    timestamp: Optional[datetime] = None

class VehicleDetectionResult(BaseModel):
    """Result of vehicle detection analysis"""
    lane_counts: Dict[str, int]
    total_vehicles: int
    detected_vehicles: List[DetectedVehicle]
    traffic_density: float
    has_emergency_vehicle: bool = False
    detection_confidence: float
    timestamp: float
    analysis_duration_ms: Optional[float] = None

class TrafficSignal(BaseModel):
    """Individual traffic signal state"""
    lane: str
    state: SignalState
    duration_remaining_ms: int
    next_state: SignalState
    last_changed: datetime

class IntersectionStatus(BaseModel):
    """Current status of the intersection"""
    signals: Dict[str, TrafficSignal]
    active_lane: str
    cycle_count: int
    total_wait_time_ms: int
    efficiency_score: float = Field(ge=0.0, le=1.0)
    emergency_mode: bool = False
    timestamp: datetime

class EmergencyAlert(BaseModel):
    """Emergency vehicle alert"""
    id: str
    emergency_type: EmergencyType
    detected_lane: str
    priority_level: int = Field(ge=1, le=5)
    estimated_arrival_time: Optional[int] = None  # seconds
    override_duration: int = 30000  # milliseconds
    timestamp: datetime

class TrafficSnapshot(BaseModel):
    """Snapshot of traffic conditions at a point in time"""
    intersection_id: str
    vehicle_counts: Dict[str, int]
    signal_states: Dict[str, str]
    wait_times: Dict[str, int]  # average wait time per lane
    throughput: Dict[str, int]  # vehicles processed per lane
    efficiency_metrics: Dict[str, float]
    timestamp: datetime

class SystemConfiguration(BaseModel):
    """System configuration settings"""
    green_signal_base_time_ms: int = 10000
    yellow_signal_time_ms: int = 3000
    min_green_time_ms: int = 5000
    max_green_time_ms: int = 60000
    emergency_override_time_ms: int = 30000
    enable_adaptive_timing: bool = True
    enable_emergency_detection: bool = True
    enable_pedestrian_priority: bool = False
    detection_confidence_threshold: float = 0.4

class AnalyticsReport(BaseModel):
    """Traffic analytics report"""
    report_id: str
    time_period: str
    total_vehicles_processed: int
    average_wait_time_ms: float
    peak_traffic_times: List[str]
    efficiency_score: float
    emergency_responses: int
    lane_utilization: Dict[str, float]
    recommendations: List[str]
    generated_at: datetime

class WebSocketMessage(BaseModel):
    """WebSocket message structure"""
    type: str
    data: Dict
    timestamp: datetime
    client_id: Optional[str] = None
