"""Prometheus metrics collection for traffic management system"""

import time
from functools import wraps
from typing import Callable, Dict, Any

from prometheus_client import (
    Counter, Histogram, Gauge, Info, CollectorRegistry, 
    generate_latest, CONTENT_TYPE_LATEST
)
from fastapi import Request, Response
from fastapi.responses import PlainTextResponse

# Create custom registry for our metrics
registry = CollectorRegistry()

# Application info
app_info = Info(
    'traffic_system_info', 
    'Information about the traffic management system',
    registry=registry
)
app_info.info({
    'version': '2.0.0',
    'component': 'ai_traffic_management',
    'model': 'yolov8'
})

# HTTP request metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total number of HTTP requests',
    ['method', 'endpoint', 'status_code'],
    registry=registry
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    registry=registry
)

http_requests_in_progress = Gauge(
    'http_requests_in_progress',
    'Number of HTTP requests currently being processed',
    ['method', 'endpoint'],
    registry=registry
)

# Vehicle detection metrics
vehicle_detections_total = Counter(
    'vehicle_detections_total',
    'Total number of vehicle detections performed',
    ['status'],
    registry=registry
)

vehicle_detection_duration_seconds = Histogram(
    'vehicle_detection_duration_seconds',
    'Vehicle detection processing time in seconds',
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=registry
)

vehicles_detected_per_image = Histogram(
    'vehicles_detected_per_image',
    'Number of vehicles detected per image',
    buckets=[0, 1, 2, 5, 10, 20, 50],
    registry=registry
)

detection_confidence_score = Histogram(
    'detection_confidence_score',
    'Vehicle detection confidence scores',
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    registry=registry
)

# Traffic management metrics
traffic_signal_changes_total = Counter(
    'traffic_signal_changes_total',
    'Total number of traffic signal changes',
    ['intersection_id', 'signal_type'],
    registry=registry
)

traffic_signal_duration_seconds = Histogram(
    'traffic_signal_duration_seconds',
    'Duration of traffic signals in seconds',
    ['intersection_id', 'signal_type'],
    registry=registry
)

emergency_overrides_total = Counter(
    'emergency_overrides_total',
    'Total number of emergency overrides',
    ['emergency_type', 'lane'],
    registry=registry
)

active_websocket_connections = Gauge(
    'active_websocket_connections',
    'Number of active WebSocket connections',
    registry=registry
)

# System health metrics
system_uptime_seconds = Gauge(
    'system_uptime_seconds',
    'System uptime in seconds',
    registry=registry
)

cpu_usage_percent = Gauge(
    'cpu_usage_percent',
    'CPU usage percentage',
    registry=registry
)

memory_usage_bytes = Gauge(
    'memory_usage_bytes',
    'Memory usage in bytes',
    registry=registry
)

model_load_time_seconds = Gauge(
    'model_load_time_seconds',
    'Time taken to load AI model in seconds',
    registry=registry
)

# Database metrics
database_connections_active = Gauge(
    'database_connections_active',
    'Number of active database connections',
    ['database_type'],
    registry=registry
)

database_query_duration_seconds = Histogram(
    'database_query_duration_seconds',
    'Database query duration in seconds',
    ['database_type', 'operation'],
    registry=registry
)

# Error metrics
errors_total = Counter(
    'errors_total',
    'Total number of errors',
    ['error_type', 'component'],
    registry=registry
)

# File processing metrics
file_uploads_total = Counter(
    'file_uploads_total',
    'Total number of file uploads',
    ['file_type', 'status'],
    registry=registry
)

file_processing_duration_seconds = Histogram(
    'file_processing_duration_seconds',
    'File processing duration in seconds',
    ['file_type'],
    registry=registry
)


def track_requests():
    """Middleware to track HTTP requests"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs) -> Response:
            start_time = time.time()
            method = request.method
            endpoint = request.url.path
            
            # Track request start
            http_requests_in_progress.labels(method=method, endpoint=endpoint).inc()
            
            try:
                response = await func(request, *args, **kwargs)
                status_code = response.status_code
                
                # Track successful request
                http_requests_total.labels(
                    method=method, 
                    endpoint=endpoint, 
                    status_code=status_code
                ).inc()
                
                return response
                
            except Exception as e:
                # Track error
                errors_total.labels(
                    error_type=type(e).__name__,
                    component='http_handler'
                ).inc()
                
                http_requests_total.labels(
                    method=method, 
                    endpoint=endpoint, 
                    status_code=500
                ).inc()
                
                raise
            
            finally:
                # Track request completion
                duration = time.time() - start_time
                http_request_duration_seconds.labels(
                    method=method, 
                    endpoint=endpoint
                ).observe(duration)
                
                http_requests_in_progress.labels(
                    method=method, 
                    endpoint=endpoint
                ).dec()
        
        return wrapper
    return decorator


def track_vehicle_detection(func: Callable) -> Callable:
    """Decorator to track vehicle detection metrics"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = await func(*args, **kwargs)
            
            # Track successful detection
            vehicle_detections_total.labels(status='success').inc()
            
            # Track detection metrics
            if hasattr(result, 'total_vehicles'):
                vehicles_detected_per_image.observe(result.total_vehicles)
            
            if hasattr(result, 'confidence_scores'):
                for score in result.confidence_scores:
                    detection_confidence_score.observe(score)
            
            return result
            
        except Exception as e:
            # Track failed detection
            vehicle_detections_total.labels(status='error').inc()
            errors_total.labels(
                error_type=type(e).__name__,
                component='vehicle_detector'
            ).inc()
            raise
        
        finally:
            # Track processing time
            duration = time.time() - start_time
            vehicle_detection_duration_seconds.observe(duration)
    
    return wrapper


def track_emergency_override(emergency_type: str, lane: str):
    """Track emergency override events"""
    emergency_overrides_total.labels(
        emergency_type=emergency_type,
        lane=lane
    ).inc()


def track_signal_change(intersection_id: str, signal_type: str, duration: float):
    """Track traffic signal changes"""
    traffic_signal_changes_total.labels(
        intersection_id=intersection_id,
        signal_type=signal_type
    ).inc()
    
    traffic_signal_duration_seconds.labels(
        intersection_id=intersection_id,
        signal_type=signal_type
    ).observe(duration)


def update_websocket_connections(count: int):
    """Update active WebSocket connections count"""
    active_websocket_connections.set(count)


def update_system_metrics(uptime: float, cpu_percent: float, memory_bytes: int):
    """Update system health metrics"""
    system_uptime_seconds.set(uptime)
    cpu_usage_percent.set(cpu_percent)
    memory_usage_bytes.set(memory_bytes)


def track_database_operation(database_type: str, operation: str, duration: float):
    """Track database operations"""
    database_query_duration_seconds.labels(
        database_type=database_type,
        operation=operation
    ).observe(duration)


def update_database_connections(database_type: str, count: int):
    """Update database connection count"""
    database_connections_active.labels(database_type=database_type).set(count)


def track_file_upload(file_type: str, status: str, processing_time: float = None):
    """Track file upload events"""
    file_uploads_total.labels(file_type=file_type, status=status).inc()
    
    if processing_time is not None:
        file_processing_duration_seconds.labels(file_type=file_type).observe(processing_time)


def get_metrics() -> str:
    """Get Prometheus metrics in text format"""
    return generate_latest(registry)


def get_metrics_response() -> PlainTextResponse:
    """Get Prometheus metrics as HTTP response"""
    return PlainTextResponse(
        content=get_metrics(),
        media_type=CONTENT_TYPE_LATEST
    )
