"""Traffic analytics: rolling summaries, lane distribution and history.

Recent observations are held in memory for fast dashboard queries and, when
persistence is enabled, also written to the database so history survives a
restart.
"""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any

from ..core.config import settings
from ..core.database import DetectionRecord, EventRecord, database
from ..core.logger import LoggerMixin
from ..models.traffic_models import (
    APPROACH_DIRECTIONS,
    LaneDirection,
    TrafficSnapshot,
    VehicleDetectionResult,
    utc_now,
)


class TrafficAnalyticsService(LoggerMixin):
    """Aggregates detections and events into reportable summaries."""

    def __init__(self, max_history_size: int = 2000) -> None:
        self.max_history_size = max_history_size
        self._detections: deque[tuple[datetime, str, VehicleDetectionResult]] = deque(maxlen=max_history_size)
        self._snapshots: deque[TrafficSnapshot] = deque(maxlen=max_history_size)
        self._hourly: dict[str, list[VehicleDetectionResult]] = defaultdict(list)
        self._service_started_at = utc_now()
        self._ready = False

        self.performance_metrics: dict[str, Any] = {
            "total_detections": 0,
            "total_vehicles_observed": 0,
            "average_vehicles_per_detection": 0.0,
            "peak_vehicles_observed": 0,
            "peak_observed_at": None,
            "busiest_lane": None,
            "emergency_events": 0,
        }

    async def initialize(self) -> None:
        self._ready = True
        self.logger.info("Analytics service initialised")

    def is_ready(self) -> bool:
        return self._ready

    async def cleanup(self) -> None:
        self._detections.clear()
        self._snapshots.clear()
        self._hourly.clear()
        self._ready = False

    @property
    def uptime_seconds(self) -> float:
        return (utc_now() - self._service_started_at).total_seconds()

    # --- ingestion -----------------------------------------------------------
    async def record_detection(
        self,
        detection_result: VehicleDetectionResult,
        timestamp: datetime | None = None,
        intersection_id: str = "main_intersection",
    ) -> None:
        """Record a detection in memory and, if enabled, in the database."""
        moment = timestamp or utc_now()

        self._detections.append((moment, intersection_id, detection_result))
        self._hourly[moment.strftime("%Y-%m-%d_%H")].append(detection_result)
        self._update_running_metrics(detection_result, moment)

        await self._persist_detection(detection_result, moment, intersection_id)

    async def _persist_detection(
        self, result: VehicleDetectionResult, moment: datetime, intersection_id: str
    ) -> None:
        async with database.session() as session:
            if session is None:
                return
            session.add(
                DetectionRecord(
                    detection_id=result.detection_id,
                    intersection_id=intersection_id,
                    recorded_at=moment,
                    total_vehicles=result.total_vehicles,
                    passenger_car_units=result.total_passenger_car_units,
                    pedestrian_count=result.pedestrian_count,
                    processing_time=result.processing_time,
                    source=result.source,
                    has_emergency=result.has_emergency_vehicles,
                    lane_counts={lane.value: count for lane, count in result.lane_counts.items()},
                )
            )

    async def record_event(
        self, event_type: str, payload: dict[str, Any], intersection_id: str = "main_intersection"
    ) -> None:
        """Persist a notable event (emergency, pedestrian phase, fault)."""
        if event_type.startswith("emergency"):
            self.performance_metrics["emergency_events"] += 1

        async with database.session() as session:
            if session is None:
                return
            session.add(
                EventRecord(
                    intersection_id=intersection_id,
                    recorded_at=utc_now(),
                    event_type=event_type,
                    payload=payload,
                )
            )

    async def record_traffic_snapshot(self, snapshot: TrafficSnapshot) -> None:
        self._snapshots.append(snapshot)
        if snapshot.has_active_emergencies():
            self.performance_metrics["emergency_events"] += 1

    def _update_running_metrics(self, result: VehicleDetectionResult, moment: datetime) -> None:
        metrics_map = self.performance_metrics
        metrics_map["total_detections"] += 1
        metrics_map["total_vehicles_observed"] += result.total_vehicles

        total = metrics_map["total_detections"]
        metrics_map["average_vehicles_per_detection"] = round(
            metrics_map["total_vehicles_observed"] / total, 2
        )

        if result.total_vehicles > metrics_map["peak_vehicles_observed"]:
            metrics_map["peak_vehicles_observed"] = result.total_vehicles
            metrics_map["peak_observed_at"] = moment.isoformat()

        busiest = result.busiest_lane
        if busiest is not None:
            metrics_map["busiest_lane"] = busiest.value

    # --- summaries -----------------------------------------------------------
    async def generate_summary(self, period: str = "current") -> dict[str, Any]:
        """Analytics summary for ``current``, ``hourly`` or ``daily``."""
        generators = {
            "current": self._current_summary,
            "hourly": self._hourly_summary,
            "daily": self._daily_summary,
        }
        generator = generators.get(period, self._current_summary)
        return await generator()

    async def _current_summary(self) -> dict[str, Any]:
        now = utc_now()
        recent = list(self._detections)[-20:]

        summary: dict[str, Any] = {
            "period": "current",
            "timestamp": now.isoformat(),
            "session_duration_seconds": round(self.uptime_seconds, 1),
            "performance_metrics": dict(self.performance_metrics),
            "detection_count": len(self._detections),
            "snapshot_count": len(self._snapshots),
            "persistence_enabled": database.is_available,
        }

        if recent:
            vehicle_counts = [result.total_vehicles for _, _, result in recent]
            processing_times = [result.processing_time for _, _, result in recent]
            summary["recent_traffic"] = {
                "sample_size": len(recent),
                "average_vehicles": round(statistics.fmean(vehicle_counts), 2),
                "median_vehicles": round(statistics.median(vehicle_counts), 2),
                "peak_vehicles": max(vehicle_counts),
                "lane_distribution_percent": self._lane_distribution(recent),
                "pedestrians_observed": sum(result.pedestrian_count for _, _, result in recent),
                "detections_with_emergency": sum(
                    1 for _, _, result in recent if result.has_emergency_vehicles
                ),
            }
            summary["pipeline_health"] = {
                "average_processing_seconds": round(statistics.fmean(processing_times), 4),
                "slowest_processing_seconds": round(max(processing_times), 4),
                "average_confidence": self._average_confidence(recent),
            }

        if len(self._detections) >= 4:
            summary["traffic_flow"] = self._flow_trend()

        elapsed_minutes = max(self.uptime_seconds / 60.0, 1 / 60.0)
        summary["system_health"] = {
            "detections_per_minute": round(len(self._detections) / elapsed_minutes, 2),
            "data_points_collected": len(self._detections) + len(self._snapshots),
        }

        return summary

    async def _hourly_summary(self) -> dict[str, Any]:
        key = utc_now().strftime("%Y-%m-%d_%H")
        results = self._hourly.get(key, [])

        if not results:
            return {"period": "hourly", "hour": key, "message": "No data recorded for the current hour yet."}

        lane_totals: dict[str, int] = defaultdict(int)
        for result in results:
            for lane, count in result.lane_counts.items():
                lane_totals[lane.value] += count

        vehicle_counts = [result.total_vehicles for result in results]
        return {
            "period": "hourly",
            "hour": key,
            "detections": len(results),
            "total_vehicles": sum(vehicle_counts),
            "average_vehicles_per_detection": round(statistics.fmean(vehicle_counts), 2),
            "peak_vehicles": max(vehicle_counts),
            "lane_totals": dict(lane_totals),
            "busiest_lane": max(lane_totals, key=lambda lane: lane_totals[lane]) if lane_totals else None,
        }

    async def _daily_summary(self) -> dict[str, Any]:
        today = utc_now().strftime("%Y-%m-%d")
        hourly_pattern: dict[str, int] = {}
        results: list[VehicleDetectionResult] = []

        for key, entries in self._hourly.items():
            if not key.startswith(today):
                continue
            hour = key.split("_")[1]
            hourly_pattern[hour] = sum(entry.total_vehicles for entry in entries)
            results.extend(entries)

        if not results:
            return {"period": "daily", "date": today, "message": "No data recorded today yet."}

        peak_hour = max(hourly_pattern, key=lambda hour: hourly_pattern[hour]) if hourly_pattern else None
        return {
            "period": "daily",
            "date": today,
            "detections": len(results),
            "total_vehicles": sum(result.total_vehicles for result in results),
            "hourly_pattern": dict(sorted(hourly_pattern.items())),
            "peak_hour": peak_hour,
            "peak_hour_vehicles": hourly_pattern.get(peak_hour, 0) if peak_hour else 0,
            "detections_with_emergency": sum(1 for result in results if result.has_emergency_vehicles),
        }

    # --- derived views -------------------------------------------------------
    @staticmethod
    def _lane_distribution(records: list[tuple[datetime, str, VehicleDetectionResult]]) -> dict[str, float]:
        """Share of observed vehicles per approach, as percentages."""
        lane_totals: dict[LaneDirection, int] = dict.fromkeys(APPROACH_DIRECTIONS, 0)
        total = 0

        for _, _, result in records:
            for lane, count in result.lane_counts.items():
                if lane in lane_totals:
                    lane_totals[lane] += count
                    total += count

        if total == 0:
            return {lane.value: 0.0 for lane in APPROACH_DIRECTIONS}

        return {lane.value: round(count * 100.0 / total, 1) for lane, count in lane_totals.items()}

    @staticmethod
    def _average_confidence(records: list[tuple[datetime, str, VehicleDetectionResult]]) -> float:
        scores = [vehicle.confidence for _, _, result in records for vehicle in result.detected_vehicles]
        return round(statistics.fmean(scores), 3) if scores else 0.0

    def _flow_trend(self) -> dict[str, Any]:
        """Whether demand is rising or falling, comparing two recent halves."""
        recent = list(self._detections)[-20:]
        midpoint = len(recent) // 2
        earlier = [result.total_vehicles for _, _, result in recent[:midpoint]]
        later = [result.total_vehicles for _, _, result in recent[midpoint:]]

        if not earlier or not later:
            return {}

        earlier_mean = statistics.fmean(earlier)
        later_mean = statistics.fmean(later)
        difference = later_mean - earlier_mean

        if abs(difference) < 0.5:
            trend = "stable"
        elif difference > 0:
            trend = "increasing"
        else:
            trend = "decreasing"

        return {
            "trend": trend,
            "change_percent": round(100.0 * difference / max(earlier_mean, 1.0), 1),
            "earlier_average": round(earlier_mean, 2),
            "later_average": round(later_mean, 2),
        }

    async def get_traffic_heatmap_data(self, hours: int = 24) -> dict[str, Any]:
        """Vehicle counts bucketed by hour and approach, for a heatmap view."""
        cutoff = utc_now() - timedelta(hours=hours)
        buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for moment, _, result in self._detections:
            if moment < cutoff:
                continue
            hour = moment.strftime("%H")
            for lane, count in result.lane_counts.items():
                buckets[hour][lane.value] += count

        if not buckets:
            return {"time_range_hours": hours, "data": {}, "message": "No data in the requested window."}

        peak_hour = max(buckets, key=lambda hour: sum(buckets[hour].values()))
        return {
            "time_range_hours": hours,
            "data": {hour: dict(lanes) for hour, lanes in sorted(buckets.items())},
            "peak_hour": peak_hour,
        }

    async def get_history(
        self, intersection_id: str | None = None, hours: int = 24, limit: int = 500
    ) -> dict[str, Any]:
        """Historical detections, read from the database when available."""
        since = utc_now() - timedelta(hours=hours)

        records = await database.recent_detections(intersection_id=intersection_id, since=since, limit=limit)
        if records:
            return {
                "source": "database",
                "since": since.isoformat(),
                "count": len(records),
                "records": [
                    {
                        "detection_id": record.detection_id,
                        "intersection_id": record.intersection_id,
                        "recorded_at": record.recorded_at.isoformat(),
                        "total_vehicles": record.total_vehicles,
                        "passenger_car_units": record.passenger_car_units,
                        "pedestrian_count": record.pedestrian_count,
                        "source": record.source,
                        "lane_counts": record.lane_counts,
                    }
                    for record in records
                ],
            }

        in_memory = [
            {
                "detection_id": result.detection_id,
                "intersection_id": intersection,
                "recorded_at": moment.isoformat(),
                "total_vehicles": result.total_vehicles,
                "passenger_car_units": result.total_passenger_car_units,
                "pedestrian_count": result.pedestrian_count,
                "source": result.source,
                "lane_counts": {lane.value: count for lane, count in result.lane_counts.items()},
            }
            for moment, intersection, result in self._detections
            if moment >= since and (intersection_id is None or intersection == intersection_id)
        ][-limit:]

        return {
            "source": "memory",
            "since": since.isoformat(),
            "count": len(in_memory),
            "records": in_memory,
            "note": (
                "Persistence is disabled or empty, so only this process's history is available. "
                "Set TRAFFIC_PERSISTENCE_ENABLED=true to retain history across restarts."
            ),
        }

    async def get_performance_report(self) -> dict[str, Any]:
        """Detailed report on data collection and pipeline throughput."""
        uptime = self.uptime_seconds
        processing_times = [result.processing_time for _, _, result in self._detections]

        return {
            "service_uptime": {
                "seconds": round(uptime, 1),
                "hours": round(uptime / 3600.0, 3),
            },
            "data_collection": {
                "detections_recorded": len(self._detections),
                "snapshots_recorded": len(self._snapshots),
                "detections_per_minute": round(len(self._detections) / max(uptime / 60.0, 1 / 60.0), 2),
                "persistence_enabled": database.is_available,
                "retention_days": settings.retention_days,
            },
            "traffic_insights": {
                "total_vehicles_observed": self.performance_metrics["total_vehicles_observed"],
                "peak_vehicles_observed": self.performance_metrics["peak_vehicles_observed"],
                "busiest_lane": self.performance_metrics["busiest_lane"],
                "emergency_events": self.performance_metrics["emergency_events"],
            },
            "pipeline": {
                "average_processing_seconds": (
                    round(statistics.fmean(processing_times), 4) if processing_times else 0.0
                ),
                "p95_processing_seconds": self._percentile(processing_times, 95),
                "average_confidence": self._average_confidence(list(self._detections)),
            },
        }

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(int(len(ordered) * percentile / 100.0), len(ordered) - 1)
        return round(ordered[index], 4)
