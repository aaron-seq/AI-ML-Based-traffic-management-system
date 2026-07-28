"""Short-term traffic forecasting.

Knowing what demand is *about to* arrive lets the controller pre-allocate green
instead of only reacting to queues that have already formed.

The model deliberately avoids a heavy ML dependency. It combines:

* an exponentially weighted moving average of recent observations, which tracks
  the current trend, with
* a time-of-day (and weekday/weekend) seasonal profile learned from history,
  which captures the daily rush-hour shape.

Prediction intervals come from the residual spread, so a noisy approach honestly
reports wide bounds rather than false precision. With little history the service
says so via a low ``confidence`` rather than extrapolating confidently from
three data points.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import datetime, timedelta

from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import (
    CongestionLevel,
    ForecastPoint,
    LaneDirection,
    TrafficForecast,
    utc_now,
)

#: Observations retained per series. At one sample a minute this is ~24 hours.
_MAX_SERIES_LENGTH = 1440

#: Seasonal buckets: (is_weekend, hour-of-day).
_SeasonKey = tuple[bool, int]


class _Series:
    """Observation history for one intersection/lane pair."""

    def __init__(self) -> None:
        self.observations: deque[tuple[datetime, float]] = deque(maxlen=_MAX_SERIES_LENGTH)
        self.level: float | None = None
        self.seasonal_totals: dict[_SeasonKey, list[float]] = defaultdict(list)

    def record(self, timestamp: datetime, value: float, alpha: float) -> None:
        self.observations.append((timestamp, value))
        self.level = value if self.level is None else alpha * value + (1 - alpha) * self.level

        bucket = self.seasonal_totals[(timestamp.weekday() >= 5, timestamp.hour)]
        bucket.append(value)
        # Keep each seasonal bucket bounded; recent weeks matter more than old ones.
        if len(bucket) > 200:
            del bucket[: len(bucket) - 200]

    @property
    def count(self) -> int:
        return len(self.observations)

    def overall_mean(self) -> float:
        if not self.observations:
            return 0.0
        return statistics.fmean(value for _, value in self.observations)

    def seasonal_factor(self, moment: datetime) -> float:
        """How busy this hour usually is relative to the series average.

        Returns 1.0 when there is not enough history for the bucket, which makes
        the forecast fall back to the plain EWMA level.
        """
        overall = self.overall_mean()
        if overall <= 0:
            return 1.0

        bucket = self.seasonal_totals.get((moment.weekday() >= 5, moment.hour), [])
        if len(bucket) < 3:
            return 1.0

        return statistics.fmean(bucket) / overall

    def residual_spread(self) -> float:
        """Standard deviation of recent observations, used for the interval."""
        values = [value for _, value in self.observations]
        if len(values) < 2:
            return 0.0
        return statistics.pstdev(values)


class TrafficForecastService(LoggerMixin):
    """Maintains per-lane demand series and produces short-term forecasts."""

    def __init__(self) -> None:
        self._series: dict[tuple[str, LaneDirection | None], _Series] = defaultdict(_Series)
        self._ready = False

    async def initialize(self) -> None:
        self._ready = True
        self.logger.info("Forecast service initialised")

    def is_ready(self) -> bool:
        return self._ready

    async def cleanup(self) -> None:
        self._series.clear()
        self._ready = False

    # --- ingestion -----------------------------------------------------------
    def record_observation(
        self,
        intersection_id: str,
        lane_counts: dict[LaneDirection, int],
        timestamp: datetime | None = None,
    ) -> None:
        """Record one demand measurement for an intersection and its approaches."""
        moment = timestamp or utc_now()
        alpha = settings.forecast_smoothing_alpha

        total = 0
        for lane, count in lane_counts.items():
            self._series[(intersection_id, lane)].record(moment, float(count), alpha)
            total += count

        self._series[(intersection_id, None)].record(moment, float(total), alpha)

    def observation_count(self, intersection_id: str, lane: LaneDirection | None = None) -> int:
        return self._series[(intersection_id, lane)].count

    # --- prediction ----------------------------------------------------------
    def forecast(
        self,
        intersection_id: str,
        lane: LaneDirection | None = None,
        horizons_minutes: Iterable[int] = (5, 15, 30, 60),
    ) -> TrafficForecast:
        """Predict demand at each requested horizon."""
        series = self._series[(intersection_id, lane)]
        generated_at = utc_now()

        if series.count < settings.forecast_min_observations:
            return TrafficForecast(
                intersection_id=intersection_id,
                lane=lane,
                generated_at=generated_at,
                observations_used=series.count,
                confidence=0.0,
                points=[],
                notes=(
                    f"Need at least {settings.forecast_min_observations} observations to forecast; "
                    f"have {series.count}. Feed detections or counts in and retry."
                ),
            )

        level = series.level or series.overall_mean()
        spread = series.residual_spread()
        confidence = self._confidence(series.count, level, spread)

        points: list[ForecastPoint] = []
        for horizon in sorted(set(horizons_minutes)):
            target_time = generated_at + timedelta(minutes=horizon)
            expected = max(0.0, level * series.seasonal_factor(target_time))

            # Uncertainty grows with the horizon: doubling the lead time widens
            # the interval by sqrt(2), the usual random-walk assumption.
            widening = math.sqrt(max(horizon, 1) / 5.0)
            margin = 1.96 * spread * widening

            points.append(
                ForecastPoint(
                    horizon_minutes=horizon,
                    predicted_at=target_time,
                    expected_vehicles=round(expected, 2),
                    lower_bound=round(max(0.0, expected - margin), 2),
                    upper_bound=round(expected + margin, 2),
                    expected_congestion=CongestionLevel.from_queue(expected),
                )
            )

        return TrafficForecast(
            intersection_id=intersection_id,
            lane=lane,
            generated_at=generated_at,
            observations_used=series.count,
            confidence=confidence,
            points=points,
        )

    @staticmethod
    def _confidence(sample_count: int, level: float, spread: float) -> float:
        """Self-assessed reliability in [0, 1].

        Rises with the amount of history and falls as the series gets noisier
        relative to its own mean.
        """
        history_score = min(1.0, sample_count / 120.0)

        if level <= 0:
            noise_score = 0.5
        else:
            coefficient_of_variation = spread / level
            noise_score = 1.0 / (1.0 + coefficient_of_variation)

        return round(max(0.0, min(1.0, 0.5 * history_score + 0.5 * noise_score)), 3)

    def forecast_all_lanes(
        self, intersection_id: str, horizons_minutes: Iterable[int] = (5, 15, 30)
    ) -> dict[str, TrafficForecast]:
        """Forecast every approach of an intersection at once."""
        return {
            lane.value: self.forecast(intersection_id, lane, horizons_minutes)
            for lane in (
                LaneDirection.NORTH,
                LaneDirection.SOUTH,
                LaneDirection.EAST,
                LaneDirection.WEST,
            )
        }
