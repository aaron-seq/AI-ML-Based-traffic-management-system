"""Emergency vehicle pre-emption."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.config import settings
from ...models.traffic_models import EmergencyAlert, EmergencyOverrideRequest
from ...services.network_coordinator import IntersectionNotFoundError
from ..deps import AnalyticsDep, NetworkDep, standard_rate_limit, verify_write_access

router = APIRouter(
    prefix="/emergency",
    tags=["emergency"],
    dependencies=[Depends(standard_rate_limit)],
)


@router.post(
    "/override",
    response_model=EmergencyAlert,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_write_access)],
    summary="Pre-empt the signals for an emergency vehicle",
)
async def trigger_override(
    request: EmergencyOverrideRequest,
    network: NetworkDep,
    analytics: AnalyticsDep,
) -> EmergencyAlert:
    """Give an approaching emergency vehicle immediate right of way.

    The request body is validated into an :class:`EmergencyAlert` before it
    reaches the controller. The previous implementation passed the raw request
    dictionary straight through, and every call failed with
    ``'dict' object has no attribute 'alert_id'``.

    Pre-emption still runs through the phase machine, so conflicting movements
    receive yellow and all-red clearance before the emergency approach turns
    green -- it never cuts straight from one green to another.
    """
    if not settings.emergency_detection_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Emergency pre-emption is disabled (TRAFFIC_EMERGENCY_DETECTION_ENABLED=false).",
        )

    try:
        controller = network.get(request.intersection_id)
    except IntersectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    alert = EmergencyAlert(
        alert_id=request.alert_id or f"emg_{uuid.uuid4().hex[:12]}",
        emergency_type=request.emergency_type,
        detected_lane=request.detected_lane,
        priority_level=request.priority_level,
        override_duration=request.override_duration or settings.emergency_override_duration,
        intersection_id=request.intersection_id,
        estimated_arrival_seconds=request.estimated_arrival_seconds,
    )

    await controller.handle_emergency_override(alert)
    await analytics.record_event("emergency_override", alert.model_dump(mode="json"), request.intersection_id)
    return alert


@router.get("/active", response_model=list[EmergencyAlert], summary="List active pre-emptions")
async def list_active_alerts(network: NetworkDep) -> list[EmergencyAlert]:
    """Every pre-emption currently holding an intersection."""
    alerts: list[EmergencyAlert] = []
    for controller in network.controllers:
        alerts.extend(controller.active_emergency_alerts)
    return alerts


@router.delete(
    "/override/{alert_id}",
    dependencies=[Depends(verify_write_access)],
    summary="Clear a pre-emption early",
)
async def clear_override(alert_id: str, network: NetworkDep) -> dict[str, Any]:
    """Release the intersection before the override window expires."""
    for controller in network.controllers:
        if await controller.clear_emergency_override(alert_id):
            return {
                "alert_id": alert_id,
                "cleared": True,
                "intersection_id": controller.intersection_id,
            }

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No active emergency alert with id {alert_id!r}.",
    )
