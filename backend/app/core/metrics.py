"""Prometheus instrumentation.

All metrics live in a private registry so importing this module never pollutes
the global default registry (which matters when tests re-import the app).
Scrape them at ``GET /metrics``.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)
from starlette.responses import Response

from .config import settings

registry = CollectorRegistry()

system_info = Info(
    "traffic_system",
    "Build and configuration information for the traffic management system",
    registry=registry,
)
system_info.info(
    {
        "version": settings.application_version,
        "environment": settings.environment,
        "model": settings.model_name,
        "device": settings.inference_device,
    }
)

# --- HTTP --------------------------------------------------------------------
http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests handled, by outcome",
    ["method", "endpoint", "status_code"],
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Wall-clock time spent handling an HTTP request",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry,
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being processed",
    ["method", "endpoint"],
    registry=registry,
)

# --- Detection ---------------------------------------------------------------
detections_total = Counter(
    "traffic_detections_total",
    "Detection runs performed, by source and outcome",
    ["source", "status"],
    registry=registry,
)

detection_duration_seconds = Histogram(
    "traffic_detection_duration_seconds",
    "Time spent in the detection pipeline",
    ["source"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=registry,
)

vehicles_detected = Histogram(
    "traffic_vehicles_detected",
    "Vehicles found per analysed frame",
    buckets=(0, 1, 2, 5, 10, 20, 50, 100),
    registry=registry,
)

detection_confidence = Histogram(
    "traffic_detection_confidence",
    "Confidence scores of accepted detections",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
    registry=registry,
)

# --- Signals -----------------------------------------------------------------
signal_phase_changes_total = Counter(
    "traffic_signal_phase_changes_total",
    "Signal phase transitions performed",
    ["intersection_id", "phase"],
    registry=registry,
)

signal_cycles_total = Counter(
    "traffic_signal_cycles_total",
    "Completed signal cycles",
    ["intersection_id"],
    registry=registry,
)

green_duration_seconds = Histogram(
    "traffic_green_duration_seconds",
    "Green durations chosen by the adaptive controller",
    ["intersection_id"],
    buckets=(5, 10, 15, 20, 30, 45, 60, 90, 120),
    registry=registry,
)

queued_vehicles = Gauge(
    "traffic_queued_vehicles",
    "Vehicles currently queued, per approach",
    ["intersection_id", "lane"],
    registry=registry,
)

# --- Events ------------------------------------------------------------------
emergency_overrides_total = Counter(
    "traffic_emergency_overrides_total",
    "Emergency pre-emptions triggered",
    ["emergency_type", "lane"],
    registry=registry,
)

pedestrian_requests_total = Counter(
    "traffic_pedestrian_requests_total",
    "Pedestrian crossing requests received",
    ["crossing"],
    registry=registry,
)

pedestrian_wait_seconds = Histogram(
    "traffic_pedestrian_wait_seconds",
    "How long pedestrians waited before being served",
    buckets=(5, 10, 20, 30, 45, 60, 90, 120, 180),
    registry=registry,
)

# --- Impact ------------------------------------------------------------------
co2_kg_avoided_total = Counter(
    "traffic_co2_kg_avoided_total",
    "Modelled CO2 avoided versus a fixed-time signal plan, in kilograms",
    ["intersection_id"],
    registry=registry,
)

delay_saved_seconds_total = Counter(
    "traffic_delay_saved_seconds_total",
    "Modelled vehicle-delay saved versus a fixed-time signal plan",
    ["intersection_id"],
    registry=registry,
)

# --- Infrastructure ----------------------------------------------------------
websocket_connections = Gauge(
    "traffic_websocket_connections",
    "Open WebSocket connections",
    registry=registry,
)

errors_total = Counter(
    "traffic_errors_total",
    "Unhandled errors, by type and component",
    ["error_type", "component"],
    registry=registry,
)


# --- Recording helpers -------------------------------------------------------
def record_detection(source: str, duration: float, vehicle_count: int, confidences: list[float]) -> None:
    """Record a successful detection run."""
    detections_total.labels(source=source, status="success").inc()
    detection_duration_seconds.labels(source=source).observe(duration)
    vehicles_detected.observe(vehicle_count)
    for score in confidences:
        detection_confidence.observe(score)


def record_detection_failure(source: str) -> None:
    detections_total.labels(source=source, status="error").inc()


def record_phase_change(intersection_id: str, phase: str) -> None:
    signal_phase_changes_total.labels(intersection_id=intersection_id, phase=phase).inc()


def record_cycle(intersection_id: str) -> None:
    signal_cycles_total.labels(intersection_id=intersection_id).inc()


def record_green_duration(intersection_id: str, seconds: float) -> None:
    green_duration_seconds.labels(intersection_id=intersection_id).observe(seconds)


def set_queue_length(intersection_id: str, lane: str, count: float) -> None:
    queued_vehicles.labels(intersection_id=intersection_id, lane=lane).set(count)


def record_emergency_override(emergency_type: str, lane: str) -> None:
    emergency_overrides_total.labels(emergency_type=emergency_type, lane=lane).inc()


def record_pedestrian_request(crossing: str) -> None:
    pedestrian_requests_total.labels(crossing=crossing).inc()


def record_pedestrian_wait(seconds: float) -> None:
    pedestrian_wait_seconds.observe(seconds)


def record_impact(intersection_id: str, co2_kg: float, delay_seconds: float) -> None:
    """Accumulate modelled savings. Counters only move forward, so negatives
    (adaptive control doing worse than the baseline) are clamped to zero."""
    if co2_kg > 0:
        co2_kg_avoided_total.labels(intersection_id=intersection_id).inc(co2_kg)
    if delay_seconds > 0:
        delay_saved_seconds_total.labels(intersection_id=intersection_id).inc(delay_seconds)


def set_websocket_connections(count: int) -> None:
    websocket_connections.set(count)


def record_error(error_type: str, component: str) -> None:
    errors_total.labels(error_type=error_type, component=component).inc()


def get_metrics_response() -> Response:
    """Render the registry in Prometheus exposition format."""
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
