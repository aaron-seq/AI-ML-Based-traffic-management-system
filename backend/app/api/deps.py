"""FastAPI dependencies: service lookup, auth and rate limiting.

Every dependency turns a missing or not-yet-ready service into a 503 with an
actionable message, so routes never have to null-check the container.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from ..core.config import settings
from ..core.security import enforce_rate_limit, require_api_key
from ..services.adaptive_traffic_manager import AdaptiveTrafficManager
from ..services.analytics_service import TrafficAnalyticsService
from ..services.container import container
from ..services.forecast_service import TrafficForecastService
from ..services.impact_service import TrafficImpactService
from ..services.intelligent_vehicle_detector import IntelligentVehicleDetector
from ..services.network_coordinator import IntersectionNotFoundError, TrafficNetwork


def _require(service: object | None, name: str, hint: str) -> object:
    """Raise 503 unless ``service`` exists and reports itself ready."""
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The {name} service is unavailable. {hint}",
        )
    if hasattr(service, "is_ready") and not service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The {name} service is still starting up. Retry shortly.",
        )
    return service


def get_detector() -> IntelligentVehicleDetector:
    return _require(  # type: ignore[return-value]
        container.detector,
        "vehicle detection",
        "Check the startup logs: model weights may have failed to download. "
        "Counts can still be supplied via POST /api/v1/intersections/{id}/counts.",
    )


def get_network() -> TrafficNetwork:
    return _require(  # type: ignore[return-value]
        container.network, "traffic network", "The signal controller failed to start."
    )


def get_analytics() -> TrafficAnalyticsService:
    return _require(container.analytics, "analytics", "Analytics failed to start.")  # type: ignore[return-value]


def get_forecast_service() -> TrafficForecastService:
    return _require(container.forecast, "forecast", "Forecasting failed to start.")  # type: ignore[return-value]


def get_impact_service() -> TrafficImpactService:
    return _require(container.impact, "impact", "Impact modelling failed to start.")  # type: ignore[return-value]


def get_controller(
    intersection_id: str,
    network: Annotated[TrafficNetwork, Depends(get_network)],
) -> AdaptiveTrafficManager:
    """Resolve a path ``intersection_id`` to its controller, or 404."""
    try:
        return network.get(intersection_id)
    except IntersectionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{error}. List the registered intersections with GET /api/v1/intersections.",
        ) from error


def verify_write_access(request: Request) -> None:
    """Guard state-changing endpoints with the shared API key."""
    require_api_key(request)


def standard_rate_limit(request: Request) -> None:
    enforce_rate_limit(request, settings.rate_limit_requests_per_minute)


def upload_rate_limit(request: Request) -> None:
    """Tighter budget for expensive inference endpoints."""
    enforce_rate_limit(request, settings.rate_limit_upload_requests_per_minute)


# Reusable annotated aliases keep route signatures short and readable.
DetectorDep = Annotated[IntelligentVehicleDetector, Depends(get_detector)]
NetworkDep = Annotated[TrafficNetwork, Depends(get_network)]
ControllerDep = Annotated[AdaptiveTrafficManager, Depends(get_controller)]
AnalyticsDep = Annotated[TrafficAnalyticsService, Depends(get_analytics)]
ForecastDep = Annotated[TrafficForecastService, Depends(get_forecast_service)]
ImpactDep = Annotated[TrafficImpactService, Depends(get_impact_service)]
