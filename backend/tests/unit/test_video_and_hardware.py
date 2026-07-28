"""Video tracking and field-hardware delivery.

Both paths involve real I/O — decoding a video, POSTing to a controller — so
they are exercised against a generated clip and a stubbed HTTP client rather
than being left to integration testing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.config import settings
from app.models.traffic_models import (
    MINIMUM_FLOW_RATE_SAMPLE_SECONDS,
    LaneDirection,
    VehicleType,
)
from app.services.hardware_bridge import HardwareBridge
from app.services.intelligent_vehicle_detector import (
    IntelligentVehicleDetector,
    UnreadableMediaError,
    _Track,
)
from tests.conftest import FakeBox, FakeResult


def _write_clip(path: Path, frame_count: int, fps: float) -> Path:
    """Write a synthetic clip of a bright block drifting across the frame."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 240))
    if not writer.isOpened():  # pragma: no cover - depends on the OpenCV build
        pytest.skip("This OpenCV build cannot write mp4")

    for index in range(frame_count):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        x = 10 + (index * 8) % 260
        cv2.rectangle(frame, (x, 100), (x + 40, 140), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture
def long_video(tmp_path: Path) -> Path:
    """A clip past MINIMUM_FLOW_RATE_SAMPLE_SECONDS: 150 frames at 10 fps."""
    return _write_clip(tmp_path / "long.mp4", frame_count=150, fps=10.0)


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """A short synthetic clip: a bright block drifting across the frame."""
    path = tmp_path / "traffic.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240))
    if not writer.isOpened():  # pragma: no cover - depends on OpenCV build
        pytest.skip("This OpenCV build cannot write mp4")

    for index in range(30):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        x = 10 + index * 8
        cv2.rectangle(frame, (x, 100), (x + 40, 140), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()
    return path


class TrackingModelStub:
    """Returns one moving tracked car per frame, with a stable track id."""

    def __init__(self) -> None:
        self.frame_index = 0

    def track(self, _frame, **_kwargs):
        # Walk the box from the west sector towards the east sector.
        x = 100 + self.frame_index * 60
        self.frame_index += 1
        return [FakeResult([FakeBox(2, 0.9, (x, 480, x + 60, 540), track_id=7)])]


class TestTrackState:
    def test_dominant_lane_is_the_most_frequent_one(self):
        track = _Track(vehicle_type=VehicleType.CAR)
        track.lanes = [LaneDirection.NORTH, LaneDirection.NORTH, LaneDirection.EAST]

        assert track.dominant_lane() == LaneDirection.NORTH

    def test_an_empty_track_has_no_lane(self):
        assert _Track(vehicle_type=VehicleType.CAR).dominant_lane() == LaneDirection.UNKNOWN

    def test_speed_is_none_without_a_calibrated_scale(self):
        """Pixel displacement alone cannot yield a speed; inventing a scale
        would produce authoritative-looking nonsense."""
        track = _Track(vehicle_type=VehicleType.CAR)
        track.positions = [(0.1, 0.5, 0.0), (0.5, 0.5, 1.0)]

        assert track.average_speed_kph(metres_per_pixel=None, frame_width=1000) is None

    def test_speed_is_computed_from_the_supplied_scale(self):
        track = _Track(vehicle_type=VehicleType.CAR)
        # 0.2 of a 1000 px frame = 200 px; at 0.05 m/px that is 10 m in 1 s.
        track.positions = [(0.3, 0.5, 0.0), (0.5, 0.5, 1.0)]

        speed = track.average_speed_kph(metres_per_pixel=0.05, frame_width=1000)
        assert speed == pytest.approx(36.0, abs=0.5)  # 10 m/s

    def test_a_single_observation_yields_no_speed(self):
        track = _Track(vehicle_type=VehicleType.CAR)
        track.positions = [(0.5, 0.5, 0.0)]

        assert track.average_speed_kph(metres_per_pixel=0.05, frame_width=1000) is None

    def test_zero_elapsed_time_does_not_divide_by_zero(self):
        track = _Track(vehicle_type=VehicleType.CAR)
        track.positions = [(0.3, 0.5, 1.0), (0.5, 0.5, 1.0)]

        assert track.average_speed_kph(metres_per_pixel=0.05, frame_width=1000) is None


def build_detector(tracking_model: object | None = None) -> IntelligentVehicleDetector:
    """A ready detector with both model handles stubbed.

    Tracking and prediction use separate handles, so a test that stubs only one
    would fall through to loading real weights.
    """
    detector = IntelligentVehicleDetector()
    detector._ready = True
    detector._model = TrackingModelStub()
    detector._tracking_model = tracking_model or TrackingModelStub()
    return detector


class TestTrackerIsolation:
    """Regression cover for a bug that silently degraded queue counts.

    ``YOLO.track(persist=True)`` attaches stateful trackers to the model's
    predictor and leaves them attached. Sharing one handle between tracking and
    still-image detection meant a single video upload filtered every later
    ``predict()`` through stale track state: on real photos, detection fell
    from 11 vehicles to 3 and from 15 to 1, with no error raised.
    """

    async def test_tracking_uses_a_separate_handle_from_prediction(self, sample_video):
        detector = IntelligentVehicleDetector()
        detector._ready = True
        detector._model = TrackingModelStub()

        await detector.analyze_video(str(sample_video), frame_stride=1, max_frames=3)

        assert detector._tracking_model is not None
        assert detector._tracking_model is not detector._model

    async def test_the_prediction_handle_is_never_used_for_tracking(self, sample_video, monkeypatch):
        """The detection model must see no track() calls at all."""
        detection_model = TrackingModelStub()
        tracking_model = TrackingModelStub()

        detector = IntelligentVehicleDetector()
        detector._ready = True
        detector._model = detection_model
        monkeypatch.setattr(detector, "_load_model", lambda: tracking_model)

        await detector.analyze_video(str(sample_video), frame_stride=1, max_frames=5)

        assert detection_model.frame_index == 0, "the detection handle was contaminated by tracking"
        assert tracking_model.frame_index > 0

    async def test_the_first_frame_resets_tracker_state_between_videos(self, sample_video):
        """Otherwise track ids leak across uploads and inflate unique counts."""
        recorded: list[bool] = []

        class RecordingModel(TrackingModelStub):
            def track(self, frame, **kwargs):
                recorded.append(kwargs["persist"])
                return super().track(frame, **kwargs)

        detector = IntelligentVehicleDetector()
        detector._ready = True
        detector._model = TrackingModelStub()
        detector._tracking_model = RecordingModel()

        await detector.analyze_video(str(sample_video), frame_stride=1, max_frames=4)

        assert recorded[0] is False, "first frame must reinitialise the trackers"
        assert all(recorded[1:]), "later frames must persist track identity"


class TestVideoAnalysis:
    async def test_counts_a_tracked_vehicle_once_not_once_per_frame(self, sample_video):
        """This is the point of tracking: the same car in 10 frames is one
        vehicle, not ten."""
        detector = build_detector()

        result = await detector.analyze_video(str(sample_video), frame_stride=1, max_frames=10)

        assert result.frames_analysed > 1
        assert result.unique_vehicles == 1

    async def test_withholds_flow_rate_from_a_sample_that_is_too_short(self, sample_video):
        """Extrapolating an hourly rate from a 1-second clip multiplies it by
        3600 and yields a physically impossible figure. Withholding it, with an
        explanation, beats reporting authoritative nonsense."""
        detector = build_detector()

        result = await detector.analyze_video(str(sample_video), frame_stride=1, max_frames=10)

        assert result.duration_seconds > 0
        assert result.duration_seconds < MINIMUM_FLOW_RATE_SAMPLE_SECONDS
        assert result.flow_rate_vehicles_per_hour is None
        assert "withheld" in (result.sampling_note or "")

    async def test_reports_flow_rate_once_the_sample_is_long_enough(self, long_video):
        detector = build_detector()

        result = await detector.analyze_video(str(long_video), frame_stride=5, max_frames=40)

        assert result.duration_seconds >= MINIMUM_FLOW_RATE_SAMPLE_SECONDS
        assert result.flow_rate_vehicles_per_hour is not None
        assert result.flow_rate_vehicles_per_hour > 0
        assert result.sampling_note is None

    async def test_frame_stride_reduces_the_work(self, sample_video):
        detector = build_detector()
        dense = await detector.analyze_video(str(sample_video), frame_stride=1, max_frames=30)

        detector._tracking_model = TrackingModelStub()
        sparse = await detector.analyze_video(str(sample_video), frame_stride=5, max_frames=30)

        assert sparse.frames_analysed < dense.frames_analysed

    async def test_max_frames_bounds_the_request(self, sample_video):
        detector = build_detector()

        result = await detector.analyze_video(str(sample_video), frame_stride=1, max_frames=3)
        assert result.frames_analysed <= 3

    async def test_per_frame_detail_is_opt_in(self, sample_video):
        detector = build_detector()

        lean = await detector.analyze_video(str(sample_video), frame_stride=1, max_frames=5)
        assert lean.frames == []

        detector._tracking_model = TrackingModelStub()
        detailed = await detector.analyze_video(
            str(sample_video), frame_stride=1, max_frames=5, keep_frame_results=True
        )
        assert len(detailed.frames) == detailed.frames_analysed

    async def test_speeds_appear_once_a_scale_is_supplied(self, sample_video):
        detector = build_detector()

        result = await detector.analyze_video(
            str(sample_video), frame_stride=1, max_frames=10, metres_per_pixel=0.05
        )
        assert result.average_speed_kph is not None

    async def test_an_unopenable_source_is_reported_clearly(self):
        detector = build_detector()

        with pytest.raises(UnreadableMediaError, match="Could not open"):
            await detector.analyze_video("/nonexistent/path/to/clip.mp4")


class StubResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("error", request=None, response=None)  # type: ignore[arg-type]


class StubHttpClient:
    """Records the commands a bridge would send to field hardware."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.posts: list[tuple[str, dict]] = []

    async def post(self, url: str, json: dict) -> StubResponse:
        self.posts.append((url, json))
        return StubResponse(self.status_code)

    async def aclose(self) -> None:
        pass


class TestHardwareDelivery:
    async def test_delivers_a_queued_command(self, controller, monkeypatch):
        monkeypatch.setattr(settings, "hardware_webhook_url", "http://controller.local/signals")

        bridge = HardwareBridge()
        await bridge.initialize()
        client = StubHttpClient()
        bridge._client = client  # type: ignore[assignment]

        try:
            bridge.publish_state(await controller.get_current_status())
            await asyncio.wait_for(bridge._queue.join(), timeout=2)

            assert len(client.posts) == 1
            url, command = client.posts[0]
            assert url == "http://controller.local/signals"
            assert command["intersection_id"] == controller.intersection_id
            assert bridge.stats.sent == 1
        finally:
            await bridge.cleanup()

    async def test_a_failing_endpoint_is_counted_not_raised(self, controller, monkeypatch):
        """A flaky field link must never take the control loop down."""
        monkeypatch.setattr(settings, "hardware_webhook_url", "http://controller.local/signals")

        bridge = HardwareBridge()
        await bridge.initialize()
        bridge._client = StubHttpClient(status_code=500)  # type: ignore[assignment]

        try:
            bridge.publish_state(await controller.get_current_status())
            await asyncio.wait_for(bridge._queue.join(), timeout=2)

            assert bridge.stats.failed == 1
            assert bridge.stats.last_error is not None
        finally:
            await bridge.cleanup()

    async def test_a_backlog_sheds_the_oldest_command(self, controller, monkeypatch):
        """Field hardware only cares about the newest state."""
        monkeypatch.setattr(settings, "hardware_webhook_url", "http://controller.local/signals")

        bridge = HardwareBridge()
        bridge._ready = True  # queue commands without starting the worker

        status = await controller.get_current_status()
        for _ in range(100):
            bridge.publish_state(status)

        assert bridge._queue.qsize() <= 32
        assert bridge.stats.dropped > 0

    async def test_includes_an_auth_header_when_a_token_is_set(self, monkeypatch):
        monkeypatch.setattr(settings, "hardware_webhook_url", "http://controller.local/signals")
        monkeypatch.setattr(settings, "hardware_webhook_token", "field-secret")

        bridge = HardwareBridge()
        await bridge.initialize()
        try:
            assert bridge._client.headers["Authorization"] == "Bearer field-secret"
        finally:
            await bridge.cleanup()
