"""Pedestrian crossing requests and priority.

Signal systems that optimise only for vehicle throughput make crossings slower
and less safe for people on foot. These endpoints give pedestrians a first-class
place in the control loop: requests are served at the next safe phase boundary,
and a request that has waited longer than ``TRAFFIC_PEDESTRIAN_MAX_WAIT_SECONDS``
pre-empts vehicle phases outright.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.config import settings
from ...models.traffic_models import PedestrianRequest, PedestrianRequestBody
from ...services.network_coordinator import IntersectionNotFoundError
from ..deps import AnalyticsDep, NetworkDep, standard_rate_limit, verify_write_access

router = APIRouter(
    prefix="/pedestrians",
    tags=["pedestrians"],
    dependencies=[Depends(standard_rate_limit)],
)


@router.post(
    "/request",
    response_model=PedestrianRequest,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_write_access)],
    summary="Request a pedestrian crossing",
)
async def request_crossing(
    body: PedestrianRequestBody,
    network: NetworkDep,
    analytics: AnalyticsDep,
) -> PedestrianRequest:
    """Register a crossing request -- the software equivalent of the push button.

    Set ``accessibility_extension`` for crossings used by wheelchair users,
    older people or children; the walk phase is extended by half again so
    slower pedestrians are not stranded mid-carriageway.
    """
    try:
        controller = network.get(body.intersection_id)
    except IntersectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    request = await controller.request_pedestrian_crossing(
        crossing=body.crossing,
        pedestrian_count=body.pedestrian_count,
        accessibility_extension=body.accessibility_extension,
    )

    await analytics.record_event("pedestrian_request", request.model_dump(mode="json"), body.intersection_id)
    return request


@router.get(
    "/pending",
    response_model=list[PedestrianRequest],
    summary="List unserved crossing requests",
)
async def list_pending(network: NetworkDep) -> list[PedestrianRequest]:
    pending: list[PedestrianRequest] = []
    for controller in network.controllers:
        pending.extend(controller.pending_pedestrian_requests)
    return pending


@router.get("/policy", summary="Current pedestrian service policy")
async def crossing_policy() -> dict[str, Any]:
    """The timing rules the controller applies to pedestrian requests."""
    return {
        "crossing_duration_seconds": settings.pedestrian_crossing_duration,
        "accessibility_duration_seconds": int(settings.pedestrian_crossing_duration * 1.5),
        "maximum_wait_seconds": settings.pedestrian_max_wait_seconds,
        "behaviour": (
            "Requests are served at the next all-red boundary. A request waiting longer than the "
            "maximum pre-empts the running vehicle phase, so pedestrian delay is bounded regardless "
            "of how heavy vehicle demand is."
        ),
    }
