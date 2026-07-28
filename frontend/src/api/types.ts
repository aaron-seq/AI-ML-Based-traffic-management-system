/**
 * Types mirroring the backend Pydantic schemas in
 * `backend/app/models/traffic_models.py`.
 *
 * Keep them in step with the API: `GET /api/openapi.json` is the source of
 * truth when the two drift.
 */

export type SignalState =
  | 'red'
  | 'yellow'
  | 'green'
  | 'flashing_red'
  | 'flashing_yellow'
  | 'off';

export type LaneDirection = 'north' | 'south' | 'east' | 'west' | 'unknown';

export type SignalPhase =
  | 'north_south_green'
  | 'north_south_yellow'
  | 'east_west_green'
  | 'east_west_yellow'
  | 'all_red'
  | 'pedestrian_crossing'
  | 'emergency_preemption';

export type CongestionLevel = 'free_flow' | 'light' | 'moderate' | 'heavy' | 'congested';

export type VehicleType =
  | 'car'
  | 'truck'
  | 'bus'
  | 'motorcycle'
  | 'bicycle'
  | 'train'
  | 'emergency'
  | 'pedestrian';

export type EmergencyType = 'ambulance' | 'fire_truck' | 'police' | 'rescue' | 'other';

export interface BoundingBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  area: number;
}

export interface DetectedVehicle {
  vehicle_type: VehicleType;
  confidence: number;
  bounding_box: BoundingBox;
  center: { x: number; y: number };
  lane: LaneDirection;
  is_emergency: boolean;
  track_id: number | null;
  speed_kph: number | null;
  detection_timestamp: string;
  passenger_car_units: number;
}

export interface LaneStatistics {
  lane: LaneDirection;
  vehicle_count: number;
  passenger_car_units: number;
  average_speed_kph: number | null;
  emergency_vehicles: number;
  pedestrians_waiting: number;
  congestion_level: CongestionLevel;
}

export interface TrafficSignal {
  signal_id: string;
  direction: LaneDirection;
  current_state: SignalState;
  remaining_time: number;
  next_state: SignalState | null;
  cycle_duration: number;
  last_updated: string;
}

export interface IntersectionStatus {
  intersection_id: string;
  name: string;
  current_phase: SignalPhase;
  phase_elapsed_seconds: number;
  traffic_signals: Partial<Record<LaneDirection, TrafficSignal>>;
  vehicle_counts: Partial<Record<LaneDirection, number>>;
  lane_statistics: Partial<Record<LaneDirection, LaneStatistics>>;
  total_vehicles: number;
  average_wait_time: number;
  cycles_completed: number;
  emergency_mode_active: boolean;
  pedestrian_phase_active: boolean;
  pending_pedestrian_requests: number;
  adaptive_mode: boolean;
  system_status: string;
  last_detection_time: string | null;
  last_updated: string;
  green_direction: LaneDirection[];
  congestion_level: CongestionLevel;
}

export interface IntersectionSummary {
  intersection_id: string;
  name: string;
  current_phase: SignalPhase;
  total_vehicles: number;
  congestion_level: CongestionLevel;
  emergency_mode_active: boolean;
  last_updated: string;
}

export interface DetectionResult {
  detection_id: string;
  total_vehicles: number;
  lane_counts: Partial<Record<LaneDirection, number>>;
  lane_statistics: Partial<Record<LaneDirection, LaneStatistics>>;
  detected_vehicles: DetectedVehicle[];
  pedestrian_count: number;
  processing_time: number;
  source: string;
  image_path: string | null;
  annotated_image_path: string | null;
  has_emergency_vehicles: boolean;
  detection_timestamp: string;
  total_passenger_car_units: number;
  busiest_lane: LaneDirection | null;
}

export interface VideoAnalysisResult {
  analysis_id: string;
  frames_analysed: number;
  duration_seconds: number;
  processing_time: number;
  unique_vehicles: number;
  vehicle_type_breakdown: Partial<Record<VehicleType, number>>;
  lane_counts: Partial<Record<LaneDirection, number>>;
  peak_lane_counts: Partial<Record<LaneDirection, number>>;
  average_speed_kph: number | null;
  /** Null when the sample was too short to extrapolate; see `sampling_note`. */
  flow_rate_vehicles_per_hour: number | null;
  has_emergency_vehicles: boolean;
  sampling_note: string | null;
  analysed_at: string;
}

export interface ForecastPoint {
  horizon_minutes: number;
  predicted_at: string;
  expected_vehicles: number;
  lower_bound: number;
  upper_bound: number;
  expected_congestion: CongestionLevel;
}

export interface TrafficForecast {
  intersection_id: string;
  lane: LaneDirection | null;
  generated_at: string;
  method: string;
  observations_used: number;
  confidence: number;
  points: ForecastPoint[];
  notes: string | null;
}

export interface ImpactEstimate {
  intersection_id: string;
  window_start: string;
  window_end: string;
  vehicles_served: number;
  baseline_delay_seconds: number;
  adaptive_delay_seconds: number;
  delay_saved_seconds: number;
  idling_hours_avoided: number;
  fuel_litres_saved: number;
  co2_kg_avoided: number;
  person_hours_saved: number;
  economic_value_saved: number;
  currency: string;
  assumptions: Record<string, string | number>;
  delay_reduction_percent: number;
}

export interface EmergencyAlert {
  alert_id: string;
  emergency_type: EmergencyType;
  detected_lane: LaneDirection;
  priority_level: number;
  override_duration: number;
  intersection_id: string;
  is_active: boolean;
  created_at: string;
  resolved_at: string | null;
}

export interface PedestrianRequest {
  request_id: string;
  crossing: LaneDirection;
  requested_at: string;
  served_at: string | null;
  pedestrian_count: number;
  accessibility_extension: boolean;
  waiting_seconds: number;
}

export interface ServiceHealth {
  name: string;
  ready: boolean;
  detail: string | null;
}

export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  environment: string;
  timestamp: string;
  uptime_seconds: number;
  health_score: number;
  services: ServiceHealth[];
  system: Record<string, number>;
  websocket_connections: number;
}

export interface SystemInfo {
  application_name: string;
  version: string;
  environment: string;
  debug_mode: boolean;
  docs_url: string | null;
  features: Record<string, boolean>;
  model: Record<string, string | number>;
  signal_plan: Record<string, number>;
}

export interface CoordinationPlan {
  enabled: boolean;
  design_speed_kph: number;
  common_cycle_seconds: number;
  corridor: string[];
  offsets_seconds: Record<string, number>;
  corridor_length_metres: number;
  corridor_travel_time_seconds: number;
}

export interface AnalyticsSummary {
  period: string;
  timestamp: string;
  session_duration_seconds: number;
  detection_count: number;
  persistence_enabled: boolean;
  performance_metrics: Record<string, number | string | null>;
  recent_traffic?: {
    sample_size: number;
    average_vehicles: number;
    median_vehicles: number;
    peak_vehicles: number;
    lane_distribution_percent: Record<string, number>;
    pedestrians_observed: number;
    detections_with_emergency: number;
  };
  pipeline_health?: {
    average_processing_seconds: number;
    slowest_processing_seconds: number;
    average_confidence: number;
  };
  traffic_flow?: {
    trend: string;
    change_percent: number;
    earlier_average: number;
    later_average: number;
  };
  system_health: Record<string, number>;
}

/** Envelope wrapping every WebSocket message. */
export interface WebSocketEnvelope<T = unknown> {
  type: string;
  data: T;
  timestamp: string;
}
