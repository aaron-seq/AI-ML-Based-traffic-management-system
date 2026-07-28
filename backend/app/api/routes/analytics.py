"""Analytics, forecasting and impact reporting."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...models.traffic_models import ImpactEstimate, LaneDirection, TrafficForecast
from ...services.network_coordinator import IntersectionNotFoundError
from ..deps import AnalyticsDep, ForecastDep, ImpactDep, NetworkDep, standard_rate_limit

router = APIRouter(tags=["analytics"], dependencies=[Depends(standard_rate_limit)])


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #
@router.get("/analytics/summary", summary="Traffic analytics summary")
async def analytics_summary(
    analytics: AnalyticsDep,
    period: Annotated[Literal["current", "hourly", "daily"], Query()] = "current",
) -> dict[str, Any]:
    """Rolling summary of observed traffic and pipeline health."""
    return await analytics.generate_summary(period)


@router.get("/analytics/heatmap", summary="Vehicle counts by hour and approach")
async def analytics_heatmap(
    analytics: AnalyticsDep,
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
) -> dict[str, Any]:
    """Hour-by-approach matrix suitable for a heatmap visualisation."""
    return await analytics.get_traffic_heatmap_data(hours)


@router.get("/analytics/history", summary="Historical detection records")
async def analytics_history(
    analytics: AnalyticsDep,
    intersection_id: Annotated[str | None, Query()] = None,
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> dict[str, Any]:
    """Past detections, from the database when persistence is enabled."""
    return await analytics.get_history(intersection_id=intersection_id, hours=hours, limit=limit)


@router.get("/analytics/performance", summary="Detailed performance report")
async def analytics_performance(analytics: AnalyticsDep) -> dict[str, Any]:
    return await analytics.get_performance_report()


# --------------------------------------------------------------------------- #
# Forecasting
# --------------------------------------------------------------------------- #
@router.get(
    "/forecast/{intersection_id}",
    response_model=TrafficForecast,
    summary="Short-term demand forecast",
)
async def forecast_intersection(
    intersection_id: str,
    forecast: ForecastDep,
    network: NetworkDep,
    lane: Annotated[LaneDirection | None, Query(description="Omit for the whole intersection")] = None,
    horizons: Annotated[list[int] | None, Query(description="Horizons in minutes")] = None,
) -> TrafficForecast:
    """Predict demand 5-60 minutes ahead so green can be allocated in advance.

    The forecast reports its own ``confidence`` and, when history is too thin,
    returns no points together with a note saying what is needed -- rather than
    extrapolating confidently from a handful of samples.
    """
    if not network.exists(intersection_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown intersection: {intersection_id}"
        )

    return forecast.forecast(intersection_id, lane, horizons or (5, 15, 30, 60))


@router.get("/forecast/{intersection_id}/lanes", summary="Forecast every approach")
async def forecast_all_lanes(
    intersection_id: str,
    forecast: ForecastDep,
    network: NetworkDep,
) -> dict[str, TrafficForecast]:
    if not network.exists(intersection_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown intersection: {intersection_id}"
        )
    return forecast.forecast_all_lanes(intersection_id)


# --------------------------------------------------------------------------- #
# Impact
# --------------------------------------------------------------------------- #
@router.get(
    "/impact/{intersection_id}",
    response_model=ImpactEstimate,
    summary="Estimated delay, fuel and CO2 savings",
)
async def impact_estimate(
    intersection_id: str,
    impact: ImpactDep,
    network: NetworkDep,
) -> ImpactEstimate:
    """What adaptive control is worth versus a fixed-time plan.

    Returns modelled savings in vehicle-delay, fuel, CO2, person-hours and
    money, each accompanied by the assumptions used. These are engineering
    estimates, not measurements -- re-base the factors on local fleet and fuel
    data before quoting them externally.
    """
    try:
        controller = network.get(intersection_id)
    except IntersectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return impact.estimate(await controller.get_current_status())


@router.get("/impact/{intersection_id}/cumulative", summary="Lifetime modelled savings")
async def cumulative_impact(
    intersection_id: str,
    impact: ImpactDep,
    analytics: AnalyticsDep,
    network: NetworkDep,
) -> dict[str, Any]:
    """Running totals since startup, plus a rough annual projection."""
    if not network.exists(intersection_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown intersection: {intersection_id}"
        )

    observed_hours = analytics.uptime_seconds / 3600.0
    return {
        "intersection_id": intersection_id,
        "cumulative": impact.cumulative_totals(intersection_id),
        "projection": impact.annualised_projection(intersection_id, observed_hours),
    }
