"""Shared pytest fixtures.

``ENVIRONMENT`` is forced to ``testing`` before any application module is
imported, so the settings singleton picks up the testing profile (in-memory
database, persistence off, no file logging) rather than a developer's local
``.env``.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "testing")

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.core.events import event_bus
from app.core.security import rate_limiter
from app.models.traffic_models import LaneDirection, LaneStatistics
from app.services.adaptive_traffic_manager import AdaptiveTrafficManager
from app.services.analytics_service import TrafficAnalyticsService
from app.services.forecast_service import TrafficForecastService
from app.services.impact_service import TrafficImpactService
from app.services.network_coordinator import TrafficNetwork


@pytest.fixture(autouse=True)
def reset_global_state() -> Iterator[None]:
    """Keep per-process singletons from leaking between tests."""
    rate_limiter.reset()
    event_bus.clear()
    yield
    rate_limiter.reset()
    event_bus.clear()


@pytest.fixture
def signal_plan_defaults() -> Iterator[None]:
    """Restore mutable signal-timing settings that tests may tune."""
    tunable = (
        "minimum_green_duration",
        "maximum_green_duration",
        "default_green_signal_duration",
        "yellow_signal_duration",
        "all_red_clearance_duration",
        "seconds_per_queued_vehicle",
        "pedestrian_crossing_duration",
        "pedestrian_max_wait_seconds",
        "api_key",
    )
    saved = {name: getattr(settings, name) for name in tunable}
    yield
    for name, value in saved.items():
        setattr(settings, name, value)


@pytest.fixture
async def controller() -> AsyncIterator[AdaptiveTrafficManager]:
    """An initialised controller with its control loop stopped.

    Tests drive time explicitly with ``_tick`` so they are deterministic and do
    not depend on wall-clock sleeps.
    """
    manager = AdaptiveTrafficManager(intersection_id="test_intersection", name="Test")
    await manager.initialize()
    yield manager
    await manager.cleanup()


@pytest.fixture
async def network() -> AsyncIterator[TrafficNetwork]:
    traffic_network = TrafficNetwork()
    await traffic_network.initialize()
    yield traffic_network
    await traffic_network.cleanup()


@pytest.fixture
async def analytics() -> AsyncIterator[TrafficAnalyticsService]:
    service = TrafficAnalyticsService()
    await service.initialize()
    yield service
    await service.cleanup()


@pytest.fixture
async def forecast_service() -> AsyncIterator[TrafficForecastService]:
    service = TrafficForecastService()
    await service.initialize()
    yield service
    await service.cleanup()


@pytest.fixture
async def impact_service() -> AsyncIterator[TrafficImpactService]:
    service = TrafficImpactService()
    await service.initialize()
    yield service
    await service.cleanup()


@pytest.fixture
def lane_statistics() -> dict[LaneDirection, LaneStatistics]:
    """A representative demand pattern: busy north-south, quiet east-west."""
    return {
        LaneDirection.NORTH: LaneStatistics(
            lane=LaneDirection.NORTH, vehicle_count=12, passenger_car_units=14.0
        ),
        LaneDirection.SOUTH: LaneStatistics(
            lane=LaneDirection.SOUTH, vehicle_count=8, passenger_car_units=9.5
        ),
        LaneDirection.EAST: LaneStatistics(lane=LaneDirection.EAST, vehicle_count=1, passenger_car_units=1.0),
        LaneDirection.WEST: LaneStatistics(lane=LaneDirection.WEST, vehicle_count=0, passenger_car_units=0.0),
    }


class _Scalar:
    """Mimics the 0-d tensor API the detector uses (``.item()``)."""

    def __init__(self, value: float) -> None:
        self._value = value

    def item(self) -> float:
        return self._value


class _Row:
    """Mimics a 1-d tensor row (``.tolist()``), as returned by ``box.xyxy[0]``."""

    def __init__(self, values: tuple[float, ...]) -> None:
        self._values = list(values)

    def tolist(self) -> list[float]:
        return list(self._values)


class FakeBox:
    """Stands in for one Ultralytics detection box."""

    def __init__(
        self,
        class_id: int,
        confidence: float,
        xyxy: tuple[float, float, float, float],
        track_id: int | None = None,
    ) -> None:
        self.cls = _Scalar(class_id)
        self.conf = _Scalar(confidence)
        self.xyxy = [_Row(xyxy)]
        self.id = _Scalar(track_id) if track_id is not None else None


class FakeResult:
    """Stands in for one Ultralytics ``Results`` object."""

    def __init__(self, boxes: list[FakeBox]) -> None:
        self.boxes = boxes


@pytest.fixture
def fake_detection_boxes() -> list[FakeResult]:
    """Detections spread across all four approaches, plus a pedestrian.

    Coordinates are chosen for a 1000x1000 frame so each box lands in a known
    sector: see ``assign_lane``.
    """
    return [
        FakeResult(
            [
                FakeBox(2, 0.91, (480, 100, 520, 180)),  # car, north sector
                FakeBox(2, 0.88, (480, 820, 520, 900)),  # car, south sector
                FakeBox(5, 0.79, (800, 480, 950, 520)),  # bus, east sector
                FakeBox(7, 0.72, (60, 480, 200, 520)),  # truck, west sector
                FakeBox(0, 0.65, (470, 60, 490, 120)),  # pedestrian, north
            ]
        )
    ]


@pytest.fixture
def blank_frame() -> np.ndarray:
    """A 1000x1000 BGR frame matching the fake detection coordinates."""
    return np.zeros((1000, 1000, 3), dtype=np.uint8)


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """A small real JPEG on disk, for upload and decode paths."""
    import cv2

    image = np.full((240, 320, 3), 96, dtype=np.uint8)
    path = tmp_path / "intersection.jpg"
    cv2.imwrite(str(path), image)
    return path
