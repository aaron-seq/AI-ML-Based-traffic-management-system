"""Pydantic schemas for the traffic management system.

These types are the contract between the detection pipeline, the signal
controller, the analytics/forecast services and the HTTP + WebSocket API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp.

    Replaces ``datetime.utcnow()``, which returns a naive value and is
    deprecated from Python 3.12 onwards.
    """
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class TrafficSignalState(str, Enum):
    """Displayed aspect of a signal head."""

    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    FLASHING_RED = "flashing_red"
    FLASHING_YELLOW = "flashing_yellow"
    OFF = "off"


class LaneDirection(str, Enum):
    """Approach that a lane group serves."""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    UNKNOWN = "unknown"

    @property
    def is_north_south(self) -> bool:
        return self in (LaneDirection.NORTH, LaneDirection.SOUTH)

    @property
    def opposite(self) -> "LaneDirection":
        return _OPPOSITE_DIRECTION[self]


_OPPOSITE_DIRECTION: dict[LaneDirection, LaneDirection] = {
    LaneDirection.NORTH: LaneDirection.SOUTH,
    LaneDirection.SOUTH: LaneDirection.NORTH,
    LaneDirection.EAST: LaneDirection.WEST,
    LaneDirection.WEST: LaneDirection.EAST,
    LaneDirection.UNKNOWN: LaneDirection.UNKNOWN,
}

#: The four real approaches, excluding the ``UNKNOWN`` sentinel.
APPROACH_DIRECTIONS: tuple[LaneDirection, ...] = (
    LaneDirection.NORTH,
    LaneDirection.SOUTH,
    LaneDirection.EAST,
    LaneDirection.WEST,
)


class SignalPhase(str, Enum):
    """Which movement currently holds right of way."""

    NORTH_SOUTH_GREEN = "north_south_green"
    NORTH_SOUTH_YELLOW = "north_south_yellow"
    EAST_WEST_GREEN = "east_west_green"
    EAST_WEST_YELLOW = "east_west_yellow"
    ALL_RED = "all_red"
    PEDESTRIAN_CROSSING = "pedestrian_crossing"
    EMERGENCY_PREEMPTION = "emergency_preemption"


class VehicleType(str, Enum):
    """Detected road-user classes (superset of the COCO vehicle classes)."""

    CAR = "car"
    TRUCK = "truck"
    BUS = "bus"
    MOTORCYCLE = "motorcycle"
    BICYCLE = "bicycle"
    TRAIN = "train"
    EMERGENCY = "emergency"
    PEDESTRIAN = "pedestrian"

    @property
    def is_vehicle(self) -> bool:
        """Whether this class occupies a queue at a signal."""
        return self not in (VehicleType.PEDESTRIAN,)

    @property
    def passenger_car_equivalent(self) -> float:
        """Road-capacity weight relative to one passenger car.

        Used to size queues realistically: a bus consumes far more green time
        than a motorcycle. Values follow common highway-capacity practice.
        """
        return _PASSENGER_CAR_EQUIVALENTS.get(self, 1.0)


_PASSENGER_CAR_EQUIVALENTS: dict[VehicleType, float] = {
    VehicleType.CAR: 1.0,
    VehicleType.MOTORCYCLE: 0.5,
    VehicleType.BICYCLE: 0.3,
    VehicleType.BUS: 2.5,
    VehicleType.TRUCK: 2.0,
    VehicleType.TRAIN: 3.0,
    VehicleType.EMERGENCY: 1.5,
    VehicleType.PEDESTRIAN: 0.0,
}


class EmergencyType(str, Enum):
    AMBULANCE = "ambulance"
    FIRE_TRUCK = "fire_truck"
    POLICE = "police"
    RESCUE = "rescue"
    OTHER = "other"


class CongestionLevel(str, Enum):
    """Human-readable banding of traffic density."""

    FREE_FLOW = "free_flow"
    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"
    CONGESTED = "congested"

    @classmethod
    def from_queue(cls, passenger_car_units: float) -> "CongestionLevel":
        if passenger_car_units <= 2:
            return cls.FREE_FLOW
        if passenger_car_units <= 6:
            return cls.LIGHT
        if passenger_car_units <= 12:
            return cls.MODERATE
        if passenger_car_units <= 20:
            return cls.HEAVY
        return cls.CONGESTED


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
class BoundingBox(BaseModel):
    """Pixel-space bounding box, top-left origin."""

    x1: int = Field(..., ge=0)
    y1: int = Field(..., ge=0)
    x2: int = Field(..., ge=0)
    y2: int = Field(..., ge=0)

    @field_validator("x2")
    @classmethod
    def _x2_after_x1(cls, value: int, info: Any) -> int:
        x1 = info.data.get("x1")
        if x1 is not None and value <= x1:
            raise ValueError("x2 must be greater than x1")
        return value

    @field_validator("y2")
    @classmethod
    def _y2_after_y1(cls, value: int, info: Any) -> int:
        y1 = info.data.get("y1")
        if y1 is not None and value <= y1:
            raise ValueError("y2 must be greater than y1")
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def area(self) -> int:
        return (self.x2 - self.x1) * (self.y2 - self.y1)


class NormalisedPoint(BaseModel):
    """A point expressed as a fraction of image width/height."""

    x: Annotated[float, Field(ge=0.0, le=1.0)]
    y: Annotated[float, Field(ge=0.0, le=1.0)]


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
class DetectedVehicle(BaseModel):
    """A single road user found in a frame."""

    vehicle_type: VehicleType
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    bounding_box: BoundingBox
    center: NormalisedPoint
    lane: LaneDirection
    is_emergency: bool = False
    #: Stable identity across frames when tracking is enabled.
    track_id: int | None = None
    #: Estimated speed in km/h; only available for tracked objects.
    speed_kph: Annotated[float, Field(ge=0.0)] | None = None
    detection_timestamp: datetime = Field(default_factory=utc_now)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passenger_car_units(self) -> float:
        return self.vehicle_type.passenger_car_equivalent


class LaneStatistics(BaseModel):
    """Per-approach summary derived from a set of detections."""

    lane: LaneDirection
    vehicle_count: int = Field(default=0, ge=0)
    passenger_car_units: float = Field(default=0.0, ge=0.0)
    average_speed_kph: float | None = None
    emergency_vehicles: int = Field(default=0, ge=0)
    pedestrians_waiting: int = Field(default=0, ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def congestion_level(self) -> CongestionLevel:
        return CongestionLevel.from_queue(self.passenger_car_units)


class VehicleDetectionResult(BaseModel):
    """Outcome of analysing a single image (or one sampled video frame)."""

    detection_id: str
    total_vehicles: int = Field(..., ge=0)
    lane_counts: dict[LaneDirection, int] = Field(default_factory=dict)
    lane_statistics: dict[LaneDirection, LaneStatistics] = Field(default_factory=dict)
    detected_vehicles: list[DetectedVehicle] = Field(default_factory=list)
    pedestrian_count: int = Field(default=0, ge=0)
    #: Seconds spent in the detection pipeline. Zero is legal for cached results.
    processing_time: float = Field(..., ge=0.0)
    source: str = "image"
    image_path: str | None = None
    annotated_image_path: str | None = None
    has_emergency_vehicles: bool = False
    detection_timestamp: datetime = Field(default_factory=utc_now)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_passenger_car_units(self) -> float:
        return round(sum(stat.passenger_car_units for stat in self.lane_statistics.values()), 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def busiest_lane(self) -> LaneDirection | None:
        if not self.lane_counts:
            return None
        lane, count = max(self.lane_counts.items(), key=lambda item: item[1])
        return lane if count > 0 else None

    @field_validator("lane_counts")
    @classmethod
    def _ensure_all_lanes(cls, value: dict[LaneDirection, int]) -> dict[LaneDirection, int]:
        for lane in APPROACH_DIRECTIONS:
            value.setdefault(lane, 0)
        return value


#: Shortest sample from which an hourly flow rate is worth extrapolating.
#: Scaling a two-second clip to an hour multiplies it by 1800 and yields a
#: physically impossible figure that nonetheless looks authoritative.
MINIMUM_FLOW_RATE_SAMPLE_SECONDS = 10.0


class VideoAnalysisResult(BaseModel):
    """Aggregate of every sampled frame in a video or stream segment."""

    analysis_id: str
    frames_analysed: int = Field(..., ge=0)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    processing_time: float = Field(default=0.0, ge=0.0)
    #: Distinct tracked objects, i.e. actual vehicle count rather than
    #: per-frame detections summed up.
    unique_vehicles: int = Field(default=0, ge=0)
    vehicle_type_breakdown: dict[VehicleType, int] = Field(default_factory=dict)
    lane_counts: dict[LaneDirection, int] = Field(default_factory=dict)
    peak_lane_counts: dict[LaneDirection, int] = Field(default_factory=dict)
    average_speed_kph: float | None = None
    #: Vehicles per hour crossing the scene, extrapolated from the sample.
    #: ``None`` when the sample is too short for the extrapolation to mean
    #: anything -- see :data:`MINIMUM_FLOW_RATE_SAMPLE_SECONDS`.
    flow_rate_vehicles_per_hour: float | None = None
    has_emergency_vehicles: bool = False
    #: Set when a figure was withheld or should be read with caution.
    sampling_note: str | None = None
    frames: list[VehicleDetectionResult] = Field(default_factory=list)
    analysed_at: datetime = Field(default_factory=utc_now)


# --------------------------------------------------------------------------- #
# Signals and intersections
# --------------------------------------------------------------------------- #
class TrafficSignal(BaseModel):
    """State of one signal head."""

    signal_id: str
    direction: LaneDirection
    current_state: TrafficSignalState
    remaining_time: int = Field(..., ge=0, description="Seconds left in the current aspect")
    next_state: TrafficSignalState | None = None
    cycle_duration: int = Field(default=60, gt=0)
    last_updated: datetime = Field(default_factory=utc_now)

    def is_active(self) -> bool:
        """Whether this approach currently has right of way."""
        return self.current_state == TrafficSignalState.GREEN


class PedestrianRequest(BaseModel):
    """A pressed crossing button (or a detected waiting pedestrian)."""

    request_id: str
    crossing: LaneDirection
    requested_at: datetime = Field(default_factory=utc_now)
    served_at: datetime | None = None
    pedestrian_count: int = Field(default=1, ge=1)
    #: Set for wheelchair users, elderly or child crossings; extends the walk time.
    accessibility_extension: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def waiting_seconds(self) -> float:
        end = self.served_at or utc_now()
        return max(0.0, (end - self.requested_at).total_seconds())

    @property
    def is_served(self) -> bool:
        return self.served_at is not None


class EmergencyAlert(BaseModel):
    """Request to pre-empt the signal for an emergency vehicle."""

    alert_id: str
    emergency_type: EmergencyType
    detected_lane: LaneDirection
    priority_level: Annotated[int, Field(ge=1, le=5)] = 3
    vehicle_location: NormalisedPoint | None = None
    estimated_arrival_seconds: Annotated[int, Field(ge=0)] | None = None
    override_duration: Annotated[int, Field(gt=0)] = 45
    intersection_id: str = "main_intersection"
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None

    def seconds_since_alert(self) -> float:
        """Seconds elapsed since the alert was raised."""
        return max(0.0, (utc_now() - self.created_at).total_seconds())

    def has_expired(self) -> bool:
        return self.seconds_since_alert() >= self.override_duration


class IntersectionStatus(BaseModel):
    """Complete live state of one intersection."""

    intersection_id: str = "main_intersection"
    name: str = "Main Intersection"
    current_phase: SignalPhase = SignalPhase.ALL_RED
    phase_elapsed_seconds: int = Field(default=0, ge=0)
    traffic_signals: dict[LaneDirection, TrafficSignal] = Field(default_factory=dict)
    vehicle_counts: dict[LaneDirection, int] = Field(default_factory=dict)
    lane_statistics: dict[LaneDirection, LaneStatistics] = Field(default_factory=dict)
    total_vehicles: int = Field(default=0, ge=0)
    average_wait_time: float = Field(default=0.0, ge=0.0)
    cycles_completed: int = Field(default=0, ge=0)
    emergency_mode_active: bool = False
    pedestrian_phase_active: bool = False
    pending_pedestrian_requests: int = Field(default=0, ge=0)
    adaptive_mode: bool = True
    system_status: str = "operational"
    last_detection_time: datetime | None = None
    last_updated: datetime = Field(default_factory=utc_now)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def green_direction(self) -> list[LaneDirection]:
        return [lane for lane, signal in self.traffic_signals.items() if signal.is_active()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def congestion_level(self) -> CongestionLevel:
        total = sum(stat.passenger_car_units for stat in self.lane_statistics.values())
        return CongestionLevel.from_queue(total)


class IntersectionSummary(BaseModel):
    """Lightweight row used when listing a corridor of intersections."""

    intersection_id: str
    name: str
    current_phase: SignalPhase
    total_vehicles: int
    congestion_level: CongestionLevel
    emergency_mode_active: bool
    last_updated: datetime


class TrafficSnapshot(BaseModel):
    """Point-in-time record of the whole system, used by analytics."""

    snapshot_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    intersection_status: IntersectionStatus
    vehicle_detection_result: VehicleDetectionResult | None = None
    active_emergency_alerts: list[EmergencyAlert] = Field(default_factory=list)
    performance_metrics: dict[str, Any] = Field(default_factory=dict)
    system_health: dict[str, bool] = Field(default_factory=dict)

    def has_active_emergencies(self) -> bool:
        return any(alert.is_active for alert in self.active_emergency_alerts)


# --------------------------------------------------------------------------- #
# Forecasting and impact
# --------------------------------------------------------------------------- #
class ForecastPoint(BaseModel):
    """One step of a short-term traffic forecast."""

    horizon_minutes: int = Field(..., ge=0)
    predicted_at: datetime
    expected_vehicles: float = Field(..., ge=0.0)
    lower_bound: float = Field(..., ge=0.0)
    upper_bound: float = Field(..., ge=0.0)
    expected_congestion: CongestionLevel


class TrafficForecast(BaseModel):
    """Short-term forecast for one approach (or the whole intersection)."""

    intersection_id: str
    lane: LaneDirection | None = None
    generated_at: datetime = Field(default_factory=utc_now)
    method: str = "seasonal-ewma"
    observations_used: int = Field(default=0, ge=0)
    #: 0-1 self-assessed reliability; low when history is thin.
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    points: list[ForecastPoint] = Field(default_factory=list)
    notes: str | None = None


class ImpactEstimate(BaseModel):
    """Estimated real-world benefit of adaptive control vs a fixed-time plan.

    Every figure is a *model output*, not a measurement. The assumptions are
    reported alongside so the numbers can be audited and re-based on local data.
    """

    model_config = ConfigDict(protected_namespaces=())

    intersection_id: str
    window_start: datetime
    window_end: datetime
    vehicles_served: int = Field(default=0, ge=0)
    baseline_delay_seconds: float = Field(default=0.0, ge=0.0)
    adaptive_delay_seconds: float = Field(default=0.0, ge=0.0)
    delay_saved_seconds: float = Field(default=0.0)
    idling_hours_avoided: float = Field(default=0.0)
    fuel_litres_saved: float = Field(default=0.0)
    co2_kg_avoided: float = Field(default=0.0)
    person_hours_saved: float = Field(default=0.0)
    economic_value_saved: float = Field(default=0.0)
    currency: str = "USD"
    assumptions: dict[str, float | str] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delay_reduction_percent(self) -> float:
        if self.baseline_delay_seconds <= 0:
            return 0.0
        return round(100.0 * self.delay_saved_seconds / self.baseline_delay_seconds, 2)


# --------------------------------------------------------------------------- #
# System
# --------------------------------------------------------------------------- #
class ServiceHealth(BaseModel):
    name: str
    ready: bool
    detail: str | None = None


class SystemHealthStatus(BaseModel):
    """Payload returned by ``GET /health``."""

    status: str = Field(..., description="healthy | degraded | unhealthy")
    version: str
    environment: str
    timestamp: datetime = Field(default_factory=utc_now)
    uptime_seconds: float = Field(default=0.0, ge=0.0)
    health_score: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    services: list[ServiceHealth] = Field(default_factory=list)
    system: dict[str, float] = Field(default_factory=dict)
    websocket_connections: int = Field(default=0, ge=0)


class WebSocketEnvelope(BaseModel):
    """Every message pushed over ``/ws/traffic-updates`` uses this shape."""

    type: str
    data: Any
    timestamp: datetime = Field(default_factory=utc_now)


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class EmergencyOverrideRequest(BaseModel):
    """Body of ``POST /api/v1/emergency/override``."""

    alert_id: str | None = Field(default=None, description="Generated when omitted")
    emergency_type: EmergencyType
    detected_lane: LaneDirection
    priority_level: Annotated[int, Field(ge=1, le=5)] = 3
    override_duration: Annotated[int, Field(gt=0, le=600)] | None = None
    intersection_id: str = "main_intersection"
    estimated_arrival_seconds: Annotated[int, Field(ge=0)] | None = None


class PedestrianRequestBody(BaseModel):
    """Body of ``POST /api/v1/pedestrians/request``."""

    crossing: LaneDirection
    pedestrian_count: Annotated[int, Field(ge=1, le=200)] = 1
    accessibility_extension: bool = False
    intersection_id: str = "main_intersection"


class ManualCountUpdate(BaseModel):
    """Feed vehicle counts straight in, bypassing the camera pipeline.

    Useful for loop detectors, radar, external simulators and load tests.
    """

    counts: dict[LaneDirection, Annotated[int, Field(ge=0)]]
    intersection_id: str = "main_intersection"


class SignalPlanUpdate(BaseModel):
    """Runtime tuning of the controller without a restart."""

    adaptive_mode: bool | None = None
    minimum_green_duration: Annotated[int, Field(ge=1, le=300)] | None = None
    maximum_green_duration: Annotated[int, Field(ge=1, le=600)] | None = None
    default_green_signal_duration: Annotated[int, Field(ge=1, le=600)] | None = None
    yellow_signal_duration: Annotated[int, Field(ge=1, le=15)] | None = None
    seconds_per_queued_vehicle: Annotated[float, Field(ge=0.0, le=10.0)] | None = None


class IntersectionDefinition(BaseModel):
    """Registers an intersection in a coordinated corridor."""

    intersection_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    #: Distance in metres from the previous intersection on the corridor, used
    #: to compute green-wave offsets.
    distance_from_previous_metres: Annotated[float, Field(ge=0)] = 0.0
    latitude: float | None = None
    longitude: float | None = None
