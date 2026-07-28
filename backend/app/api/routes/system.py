"""System information, health and configuration introspection."""

from __future__ import annotations

from typing import Any

import psutil
from fastapi import APIRouter

from ...core.config import settings, validate_configuration
from ...core.database import database
from ...core.events import event_bus
from ...models.traffic_models import SystemHealthStatus, utc_now
from ...services.container import container

router = APIRouter(tags=["system"])


@router.get("/system/info", summary="Application and feature information")
async def system_info() -> dict[str, Any]:
    """What this deployment is, and which capabilities are actually live."""
    health = {service.name: service.ready for service in container.health()}

    return {
        "application_name": settings.application_name,
        "version": settings.application_version,
        "environment": settings.environment,
        "api_prefix": settings.api_prefix,
        "debug_mode": settings.debug_mode,
        "docs_url": "/api/docs" if settings.docs_enabled else None,
        "features": {
            "image_detection": health.get("vehicle_detector", False),
            "video_and_stream_analysis": health.get("vehicle_detector", False),
            "vehicle_tracking": health.get("vehicle_detector", False),
            "adaptive_signal_control": health.get("traffic_network", False),
            "multi_intersection_coordination": health.get("traffic_network", False),
            "green_wave": settings.green_wave_enabled,
            "emergency_preemption": settings.emergency_detection_enabled,
            "pedestrian_priority": True,
            "short_term_forecasting": health.get("forecast", False),
            "impact_modelling": health.get("impact", False),
            "manual_count_input": True,
            "persistence": database.is_available,
            "hardware_bridge": bool(settings.hardware_webhook_url),
            "websocket_streaming": True,
            "prometheus_metrics": True,
            "api_key_auth": bool(settings.api_key),
        },
        "model": {
            "name": settings.model_name,
            "device": settings.inference_device,
            "confidence_threshold": settings.detection_confidence_threshold,
            "image_size": settings.detection_image_size,
            "tracker": settings.tracker_config,
        },
        "signal_plan": {
            "minimum_green_duration": settings.minimum_green_duration,
            "maximum_green_duration": settings.maximum_green_duration,
            "default_green_signal_duration": settings.default_green_signal_duration,
            "yellow_signal_duration": settings.yellow_signal_duration,
            "all_red_clearance_duration": settings.all_red_clearance_duration,
            "seconds_per_queued_vehicle": settings.seconds_per_queued_vehicle,
        },
    }


@router.get("/system/configuration", summary="Configuration validation report")
async def configuration_report() -> dict[str, Any]:
    """Problems that would block a safe production deployment.

    Exposed so operators can check a staging environment before promoting it,
    rather than discovering the gaps from a startup log they never read.
    """
    problems = validate_configuration()
    return {
        "environment": settings.environment,
        "valid": not problems,
        "problems": problems,
        "checked_at": utc_now().isoformat(),
    }


@router.get("/system/hardware", summary="Field hardware bridge status")
async def hardware_status() -> dict[str, Any]:
    """Whether signal state is reaching physical hardware, and delivery stats."""
    if container.hardware is None:
        return {"enabled": False, "detail": "Hardware bridge not initialised."}
    return container.hardware.health()


def build_health_status() -> SystemHealthStatus:
    """Assemble the health payload shared by ``/health`` and ``/api/v1/health``."""
    services = container.health()
    ready_count = sum(1 for service in services if service.ready)
    score = ready_count / len(services) if services else 0.0

    if score >= 0.85:
        overall = "healthy"
    elif score >= 0.5:
        overall = "degraded"
    else:
        overall = "unhealthy"

    try:
        memory = psutil.virtual_memory()
        system_stats = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": memory.percent,
            "memory_used_mb": round(memory.used / 1024 / 1024, 1),
        }
    except Exception:
        # Container runtimes sometimes hide /proc; health must not depend on it.
        system_stats = {}

    return SystemHealthStatus(
        status=overall,
        version=settings.application_version,
        environment=settings.environment,
        uptime_seconds=round(container.uptime_seconds, 1),
        health_score=round(score, 3),
        services=services,
        system=system_stats,
        websocket_connections=event_bus.subscriber_count,
    )


@router.get("/health", response_model=SystemHealthStatus, summary="Health check")
async def health() -> SystemHealthStatus:
    """Per-service readiness plus host resource usage."""
    return build_health_status()
