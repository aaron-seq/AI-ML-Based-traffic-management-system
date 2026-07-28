"""Intersection registry, live status and signal-plan control."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...core.config import settings
from ...core.events import event_bus
from ...models.traffic_models import (
    IntersectionDefinition,
    IntersectionStatus,
    IntersectionSummary,
    ManualCountUpdate,
    SignalPlanUpdate,
)
from ...services.network_coordinator import DEFAULT_INTERSECTION_ID
from ..deps import ControllerDep, ForecastDep, NetworkDep, standard_rate_limit, verify_write_access

router = APIRouter(
    prefix="/intersections",
    tags=["intersections"],
    dependencies=[Depends(standard_rate_limit)],
)


@router.get("", response_model=list[IntersectionSummary], summary="List every intersection")
async def list_intersections(network: NetworkDep) -> list[IntersectionSummary]:
    """One row per registered intersection, for corridor overview screens."""
    return await network.summaries()


@router.post(
    "",
    response_model=IntersectionSummary,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_write_access)],
    summary="Register a new intersection",
)
async def create_intersection(definition: IntersectionDefinition, network: NetworkDep) -> IntersectionSummary:
    """Add an intersection to the corridor.

    ``distance_from_previous_metres`` positions it on the corridor and feeds the
    green-wave offset calculation.
    """
    try:
        await network.add_intersection(definition)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    await network.start_all()
    summaries = await network.summaries()
    return next(row for row in summaries if row.intersection_id == definition.intersection_id)


@router.get(
    "/coordination",
    summary="Green-wave coordination plan for the corridor",
)
async def coordination_plan(
    network: NetworkDep,
    design_speed_kph: Annotated[float | None, Query(gt=0, le=130)] = None,
) -> dict[str, Any]:
    """Offsets that let a platoon cross the corridor without stopping.

    Each intersection's green starts ``distance / speed`` seconds after the
    previous one, so vehicles travelling at the design speed meet a green at
    every junction.
    """
    return await network.coordination_plan(design_speed_kph)


@router.get("/metrics", summary="Aggregate metrics across the corridor")
async def corridor_metrics(network: NetworkDep) -> dict[str, Any]:
    return network.aggregate_metrics()


@router.get(
    "/{intersection_id}",
    response_model=IntersectionStatus,
    summary="Live status of one intersection",
)
async def get_intersection_status(controller: ControllerDep) -> IntersectionStatus:
    """Current phase, per-approach signal aspects, queues and congestion level."""
    return await controller.get_current_status()


@router.delete(
    "/{intersection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_write_access)],
    summary="Deregister an intersection",
)
async def delete_intersection(intersection_id: str, network: NetworkDep) -> None:
    if intersection_id == DEFAULT_INTERSECTION_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The default intersection {DEFAULT_INTERSECTION_ID!r} cannot be removed.",
        )
    if not network.exists(intersection_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown intersection: {intersection_id}"
        )

    await network.remove_intersection(intersection_id)


@router.post(
    "/{intersection_id}/counts",
    response_model=IntersectionStatus,
    dependencies=[Depends(verify_write_access)],
    summary="Submit vehicle counts directly",
)
async def submit_counts(
    intersection_id: str,
    payload: ManualCountUpdate,
    controller: ControllerDep,
    forecast: ForecastDep,
) -> IntersectionStatus:
    """Drive the controller from a non-camera source.

    Inductive loops, radar, an external simulator or a load test can feed
    demand here without going through the detection pipeline -- which also
    means the system stays useful on hardware that cannot run inference.
    """
    await controller.update_vehicle_counts(payload.counts)
    forecast.record_observation(intersection_id, payload.counts)

    status_payload = await controller.get_current_status()
    event_bus.publish("counts_updated", status_payload.model_dump(mode="json"))
    return status_payload


@router.patch(
    "/{intersection_id}/plan",
    dependencies=[Depends(verify_write_access)],
    summary="Retune the signal plan at runtime",
)
async def update_signal_plan(update: SignalPlanUpdate, controller: ControllerDep) -> dict[str, Any]:
    """Change timing parameters, or switch between adaptive and fixed-time."""
    try:
        applied = await controller.apply_plan_update(update)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error

    return {
        "intersection_id": controller.intersection_id,
        "applied": applied,
        "current_plan": {
            "adaptive_mode": controller.status.adaptive_mode,
            "minimum_green_duration": settings.minimum_green_duration,
            "maximum_green_duration": settings.maximum_green_duration,
            "default_green_signal_duration": settings.default_green_signal_duration,
            "yellow_signal_duration": settings.yellow_signal_duration,
            "all_red_clearance_duration": settings.all_red_clearance_duration,
            "seconds_per_queued_vehicle": settings.seconds_per_queued_vehicle,
        },
    }


@router.post(
    "/{intersection_id}/start",
    dependencies=[Depends(verify_write_access)],
    summary="Start the control loop",
)
async def start_controller(controller: ControllerDep) -> dict[str, Any]:
    await controller.start_simulation()
    return {"intersection_id": controller.intersection_id, "running": controller.is_running}


@router.post(
    "/{intersection_id}/stop",
    dependencies=[Depends(verify_write_access)],
    summary="Stop the control loop",
)
async def stop_controller(controller: ControllerDep) -> dict[str, Any]:
    """Freeze the signals in their current aspect.

    Field hardware should fall back to flashing amber when it stops receiving
    updates; this endpoint only stops the software controller.
    """
    await controller.stop_simulation()
    return {"intersection_id": controller.intersection_id, "running": controller.is_running}


@router.get("/{intersection_id}/performance", summary="Controller performance counters")
async def controller_performance(controller: ControllerDep) -> dict[str, Any]:
    return {
        "intersection_id": controller.intersection_id,
        "running": controller.is_running,
        **controller.get_performance_metrics(),
    }
