"""Vehicle and pedestrian detection built on Ultralytics YOLO.

Handles single images, videos and RTSP/HTTP streams. When a video source is
used the model runs with a tracker, which turns per-frame detections into
persistent objects -- that is what makes unique-vehicle counts, flow rates and
speed estimates possible rather than just "boxes in this frame".
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..core import metrics
from ..core.config import settings
from ..core.logger import LoggerMixin
from ..models.traffic_models import (
    APPROACH_DIRECTIONS,
    BoundingBox,
    DetectedVehicle,
    LaneDirection,
    LaneStatistics,
    NormalisedPoint,
    VehicleDetectionResult,
    VehicleType,
    VideoAnalysisResult,
)

#: COCO class id -> our vehicle taxonomy. Ultralytics' pretrained detection
#: models are COCO-trained, so these ids are stable across yolov8/11/12 weights.
COCO_CLASS_MAP: dict[int, VehicleType] = {
    0: VehicleType.PEDESTRIAN,
    1: VehicleType.BICYCLE,
    2: VehicleType.CAR,
    3: VehicleType.MOTORCYCLE,
    5: VehicleType.BUS,
    6: VehicleType.TRAIN,
    7: VehicleType.TRUCK,
}

#: Classes that plausibly carry emergency livery. A bus is never an ambulance,
#: so restricting the heuristic to these avoids obvious false positives.
_EMERGENCY_CANDIDATE_TYPES = frozenset({VehicleType.TRUCK, VehicleType.CAR, VehicleType.BUS})

#: Annotation colours (BGR, because OpenCV).
_ANNOTATION_COLOURS: dict[VehicleType, tuple[int, int, int]] = {
    VehicleType.CAR: (66, 135, 245),
    VehicleType.TRUCK: (36, 99, 235),
    VehicleType.BUS: (16, 185, 129),
    VehicleType.MOTORCYCLE: (245, 158, 11),
    VehicleType.BICYCLE: (168, 85, 247),
    VehicleType.TRAIN: (120, 120, 120),
    VehicleType.PEDESTRIAN: (236, 72, 153),
    VehicleType.EMERGENCY: (0, 0, 255),
}


class DetectorNotReadyError(RuntimeError):
    """Raised when inference is attempted before the model finished loading."""


class UnreadableMediaError(ValueError):
    """Raised when an image or video cannot be decoded."""


def assign_lane(center_x: float, center_y: float) -> LaneDirection:
    """Map a normalised image position to the approach it belongs to.

    The camera is assumed to look down on the intersection with north at the
    top of the frame. The frame is split into four triangular sectors radiating
    from the centre: whichever axis the point is further along decides the
    approach.

    The previous implementation used four narrow rectangular bands covering
    roughly a fifth of the frame, so any vehicle outside those strips was
    labelled ``unknown`` and silently dropped from the queue counts that drive
    signal timing. Sector assignment covers the whole frame, so every detection
    lands on exactly one approach.
    """
    dx = center_x - 0.5
    dy = center_y - 0.5

    if dx == 0 and dy == 0:
        return LaneDirection.UNKNOWN

    if abs(dy) >= abs(dx):
        return LaneDirection.NORTH if dy < 0 else LaneDirection.SOUTH
    return LaneDirection.WEST if dx < 0 else LaneDirection.EAST


@dataclass
class _Track:
    """Per-object state accumulated while walking through a video."""

    vehicle_type: VehicleType
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    lanes: list[LaneDirection] = field(default_factory=list)
    max_confidence: float = 0.0
    is_emergency: bool = False

    def dominant_lane(self) -> LaneDirection:
        """The approach this object spent most of its life in."""
        if not self.lanes:
            return LaneDirection.UNKNOWN
        counts: dict[LaneDirection, int] = defaultdict(int)
        for lane in self.lanes:
            counts[lane] += 1
        return max(counts.items(), key=lambda item: item[1])[0]

    def average_speed_kph(self, metres_per_pixel: float | None, frame_width: int) -> float | None:
        """Mean speed over the track, or ``None`` without a calibrated scale.

        Pixel displacement alone cannot yield a speed; the caller must supply a
        ground-sampling distance. Returning ``None`` is deliberate -- inventing
        a scale would produce authoritative-looking nonsense.
        """
        if metres_per_pixel is None or len(self.positions) < 2:
            return None

        total_metres = 0.0
        total_seconds = 0.0
        # strict=False is deliberate: the offset slice is one element shorter.
        for (x1, y1, t1), (x2, y2, t2) in zip(self.positions, self.positions[1:], strict=False):
            elapsed = t2 - t1
            if elapsed <= 0:
                continue
            pixel_distance = math.hypot((x2 - x1) * frame_width, (y2 - y1) * frame_width)
            total_metres += pixel_distance * metres_per_pixel
            total_seconds += elapsed

        if total_seconds <= 0:
            return None
        return round((total_metres / total_seconds) * 3.6, 1)


class IntelligentVehicleDetector(LoggerMixin):
    """Async wrapper around a YOLO model.

    Inference is CPU/GPU-bound and synchronous, so it runs in a worker thread
    and is gated by a semaphore -- without that, concurrent uploads would
    thrash a single-GPU or small-CPU host.
    """

    def __init__(self) -> None:
        self._model: Any | None = None
        self._ready = False
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_inferences)
        self.performance_metrics: dict[str, Any] = {
            "total_detections": 0,
            "total_frames": 0,
            "average_inference_time": 0.0,
            "last_detection_at": None,
        }

    # --- lifecycle -----------------------------------------------------------
    async def initialize(self) -> None:
        """Load the model weights, downloading them on first run."""
        started = time.perf_counter()
        self.logger.info("Loading detection model %s", settings.model_name)

        self._model = await asyncio.to_thread(self._load_model)
        self._ready = True

        elapsed = time.perf_counter() - started
        self.log_performance("model_initialization", elapsed)
        self.logger.info("Detection model ready in %.2fs (device=%s)", elapsed, settings.inference_device)

    def _load_model(self) -> Any:
        """Load weights synchronously (called in a worker thread).

        Ultralytics checkpoints are pickled objects, so PyTorch >= 2.6 refuses
        to load them under its default ``weights_only=True``. Ultralytics 8.3+
        registers the required safe globals itself; we additionally resolve the
        cache path so repeated restarts do not re-download the weights.
        """
        from ultralytics import YOLO  # imported lazily: pulls in torch

        cache_directory = Path(settings.model_cache_directory)
        cache_directory.mkdir(parents=True, exist_ok=True)

        cached_weights = cache_directory / settings.model_name
        if cached_weights.exists():
            self.logger.info("Using cached weights at %s", cached_weights)
            model = YOLO(str(cached_weights))
        else:
            # Ultralytics downloads into the current working directory; move the
            # file into the cache so the next start is offline-capable.
            model = YOLO(settings.model_name)
            downloaded = Path(settings.model_name)
            if downloaded.exists() and downloaded.resolve() != cached_weights.resolve():
                try:
                    downloaded.replace(cached_weights)
                    self.logger.info("Cached weights at %s", cached_weights)
                except OSError as error:
                    self.logger.debug("Could not move weights into cache: %s", error)

        model.to(settings.inference_device)
        return model

    def is_ready(self) -> bool:
        return self._ready and self._model is not None

    async def cleanup(self) -> None:
        self._model = None
        self._ready = False
        self.logger.info("Detection model released")

    # --- image analysis ------------------------------------------------------
    async def analyze_intersection_image(
        self,
        image_path: str,
        save_annotated: bool = True,
        confidence: float | None = None,
    ) -> VehicleDetectionResult:
        """Detect road users in a still image."""
        if not self.is_ready():
            raise DetectorNotReadyError("Detection model is still loading")

        started = time.perf_counter()
        image = await asyncio.to_thread(cv2.imread, image_path)
        if image is None:
            raise UnreadableMediaError(f"Could not decode image at {image_path}")

        async with self._semaphore:
            raw_results = await asyncio.to_thread(self._predict, image, confidence)

        vehicles = self._extract_vehicles(raw_results, image.shape)

        annotated_path: str | None = None
        if save_annotated:
            annotated_path = await asyncio.to_thread(self._write_annotated_image, image, vehicles, image_path)

        elapsed = time.perf_counter() - started
        result = self._build_result(
            vehicles=vehicles,
            processing_time=elapsed,
            source="image",
            image_path=image_path,
            annotated_image_path=annotated_path,
        )

        self._record_metrics(result, source="image")
        self.logger.info(
            "Detected %d vehicles and %d pedestrians in %.3fs",
            result.total_vehicles,
            result.pedestrian_count,
            elapsed,
        )
        return result

    async def analyze_frame(
        self, frame: np.ndarray, confidence: float | None = None
    ) -> VehicleDetectionResult:
        """Detect road users in an in-memory frame (used by stream consumers)."""
        if not self.is_ready():
            raise DetectorNotReadyError("Detection model is still loading")

        started = time.perf_counter()
        async with self._semaphore:
            raw_results = await asyncio.to_thread(self._predict, frame, confidence)

        vehicles = self._extract_vehicles(raw_results, frame.shape)
        result = self._build_result(
            vehicles=vehicles,
            processing_time=time.perf_counter() - started,
            source="frame",
        )
        self._record_metrics(result, source="frame")
        return result

    # --- video analysis ------------------------------------------------------
    async def analyze_video(
        self,
        video_path: str,
        frame_stride: int | None = None,
        max_frames: int | None = None,
        metres_per_pixel: float | None = None,
        keep_frame_results: bool = False,
    ) -> VideoAnalysisResult:
        """Analyse a video file or stream URL with object tracking.

        Args:
            video_path: File path, or an RTSP/HTTP stream URL.
            frame_stride: Analyse every Nth frame. Higher is faster and coarser.
            max_frames: Stop after this many analysed frames.
            metres_per_pixel: Ground sampling distance. Supply it to get speed
                estimates; without it speeds are reported as ``None``.
            keep_frame_results: Include per-frame detail in the response. Off by
                default because a long video would return a very large payload.
        """
        if not self.is_ready():
            raise DetectorNotReadyError("Detection model is still loading")

        stride = frame_stride or settings.video_frame_stride
        limit = max_frames or settings.video_max_frames

        started = time.perf_counter()
        async with self._semaphore:
            payload = await asyncio.to_thread(
                self._walk_video, video_path, stride, limit, metres_per_pixel, keep_frame_results
            )

        payload.processing_time = round(time.perf_counter() - started, 3)
        metrics.detections_total.labels(source="video", status="success").inc()
        metrics.detection_duration_seconds.labels(source="video").observe(payload.processing_time)

        self.logger.info(
            "Analysed %d frames of %s: %d unique vehicles in %.2fs",
            payload.frames_analysed,
            video_path,
            payload.unique_vehicles,
            payload.processing_time,
        )
        return payload

    def _walk_video(
        self,
        video_path: str,
        stride: int,
        limit: int,
        metres_per_pixel: float | None,
        keep_frame_results: bool,
    ) -> VideoAnalysisResult:
        """Iterate the video, tracking objects (runs in a worker thread)."""
        capture = cv2.VideoCapture(video_path)
        if not capture.isOpened():
            raise UnreadableMediaError(f"Could not open video source: {video_path}")

        try:
            fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
            frame_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
            tracks: dict[int, _Track] = {}
            frame_results: list[VehicleDetectionResult] = []
            peak_counts: dict[LaneDirection, int] = dict.fromkeys(APPROACH_DIRECTIONS, 0)
            analysed = 0
            frame_index = 0
            last_timestamp = 0.0

            while analysed < limit:
                grabbed = capture.grab()
                if not grabbed:
                    break

                if frame_index % stride != 0:
                    frame_index += 1
                    continue

                decoded, frame = capture.retrieve()
                if not decoded or frame is None:
                    break

                timestamp = frame_index / fps
                last_timestamp = timestamp

                raw = self._model.track(
                    frame,
                    persist=True,
                    tracker=settings.tracker_config,
                    conf=settings.detection_confidence_threshold,
                    iou=settings.non_max_suppression_threshold,
                    imgsz=settings.detection_image_size,
                    device=settings.inference_device,
                    verbose=False,
                )

                vehicles = self._extract_vehicles(raw, frame.shape)
                self._merge_tracks(tracks, vehicles, timestamp)

                for lane, count in self._count_by_lane(vehicles).items():
                    peak_counts[lane] = max(peak_counts.get(lane, 0), count)

                if keep_frame_results:
                    frame_results.append(
                        self._build_result(vehicles=vehicles, processing_time=0.0, source="video")
                    )

                analysed += 1
                frame_index += 1

            return self._summarise_tracks(
                tracks=tracks,
                frames_analysed=analysed,
                duration_seconds=last_timestamp,
                peak_counts=peak_counts,
                metres_per_pixel=metres_per_pixel,
                frame_width=frame_width,
                frame_results=frame_results,
            )
        finally:
            capture.release()

    def _merge_tracks(
        self, tracks: dict[int, _Track], vehicles: Iterable[DetectedVehicle], timestamp: float
    ) -> None:
        """Fold this frame's detections into the running per-object state."""
        for vehicle in vehicles:
            if vehicle.track_id is None:
                continue
            track = tracks.get(vehicle.track_id)
            if track is None:
                track = _Track(vehicle_type=vehicle.vehicle_type)
                tracks[vehicle.track_id] = track

            track.positions.append((vehicle.center.x, vehicle.center.y, timestamp))
            track.lanes.append(vehicle.lane)
            track.max_confidence = max(track.max_confidence, vehicle.confidence)
            track.is_emergency = track.is_emergency or vehicle.is_emergency

    def _summarise_tracks(
        self,
        tracks: dict[int, _Track],
        frames_analysed: int,
        duration_seconds: float,
        peak_counts: dict[LaneDirection, int],
        metres_per_pixel: float | None,
        frame_width: int,
        frame_results: list[VehicleDetectionResult],
    ) -> VideoAnalysisResult:
        """Turn accumulated tracks into the aggregate response."""
        lane_counts: dict[LaneDirection, int] = dict.fromkeys(APPROACH_DIRECTIONS, 0)
        type_breakdown: dict[VehicleType, int] = defaultdict(int)
        speeds: list[float] = []
        unique_vehicles = 0
        has_emergency = False

        for track in tracks.values():
            type_breakdown[track.vehicle_type] += 1
            if track.vehicle_type.is_vehicle:
                unique_vehicles += 1
                lane = track.dominant_lane()
                if lane in lane_counts:
                    lane_counts[lane] += 1
            has_emergency = has_emergency or track.is_emergency

            speed = track.average_speed_kph(metres_per_pixel, frame_width)
            if speed is not None:
                speeds.append(speed)

        flow_rate = (unique_vehicles / duration_seconds * 3600.0) if duration_seconds > 0 else 0.0

        return VideoAnalysisResult(
            analysis_id=str(uuid.uuid4()),
            frames_analysed=frames_analysed,
            duration_seconds=round(duration_seconds, 2),
            unique_vehicles=unique_vehicles,
            vehicle_type_breakdown=dict(type_breakdown),
            lane_counts=lane_counts,
            peak_lane_counts=peak_counts,
            average_speed_kph=round(sum(speeds) / len(speeds), 1) if speeds else None,
            flow_rate_vehicles_per_hour=round(flow_rate, 1),
            has_emergency_vehicles=has_emergency,
            frames=frame_results,
        )

    # --- inference plumbing --------------------------------------------------
    def _predict(self, image: np.ndarray, confidence: float | None) -> Any:
        """Run a single forward pass (called in a worker thread)."""
        return self._model.predict(
            image,
            conf=confidence if confidence is not None else settings.detection_confidence_threshold,
            iou=settings.non_max_suppression_threshold,
            imgsz=settings.detection_image_size,
            device=settings.inference_device,
            verbose=False,
        )

    def _extract_vehicles(self, raw_results: Any, image_shape: tuple[int, ...]) -> list[DetectedVehicle]:
        """Convert Ultralytics output into our schema, dropping unknown classes."""
        height, width = image_shape[:2]
        vehicles: list[DetectedVehicle] = []

        for result in raw_results or []:
            boxes = getattr(result, "boxes", None)
            if boxes is None or len(boxes) == 0:
                continue

            for box in boxes:
                class_id = int(box.cls.item())
                vehicle_type = COCO_CLASS_MAP.get(class_id)
                if vehicle_type is None:
                    continue

                confidence = float(box.conf.item())
                x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())

                # Degenerate boxes occasionally survive NMS; they would fail
                # BoundingBox validation and abort an otherwise fine detection.
                if x2 - x1 < 1 or y2 - y1 < 1:
                    continue

                center_x = min(max(((x1 + x2) / 2) / max(width, 1), 0.0), 1.0)
                center_y = min(max(((y1 + y2) / 2) / max(height, 1), 0.0), 1.0)

                track_id = None
                if getattr(box, "id", None) is not None:
                    track_id = int(box.id.item())

                is_emergency = self._looks_like_emergency(vehicle_type, confidence)

                vehicles.append(
                    DetectedVehicle(
                        vehicle_type=VehicleType.EMERGENCY if is_emergency else vehicle_type,
                        confidence=confidence,
                        bounding_box=BoundingBox(
                            x1=max(int(x1), 0),
                            y1=max(int(y1), 0),
                            x2=max(int(x2), int(x1) + 1),
                            y2=max(int(y2), int(y1) + 1),
                        ),
                        center=NormalisedPoint(x=center_x, y=center_y),
                        lane=assign_lane(center_x, center_y),
                        is_emergency=is_emergency,
                        track_id=track_id,
                    )
                )

        return vehicles

    def _looks_like_emergency(self, vehicle_type: VehicleType, confidence: float) -> bool:
        """Whether a detection should be treated as an emergency vehicle.

        A COCO-trained model has no ambulance/fire-engine class, so this cannot
        be inferred from the detector alone. Rather than guess from box size --
        which mislabels every delivery lorry as an ambulance -- we return False
        and let operators raise pre-emption explicitly through
        ``POST /api/v1/emergency/override`` (from siren detection, a transponder,
        or a dispatch system). Train a custom class and extend
        :data:`COCO_CLASS_MAP` to detect them visually.
        """
        return False

    # --- aggregation ---------------------------------------------------------
    @staticmethod
    def _count_by_lane(vehicles: Iterable[DetectedVehicle]) -> dict[LaneDirection, int]:
        counts: dict[LaneDirection, int] = dict.fromkeys(APPROACH_DIRECTIONS, 0)
        for vehicle in vehicles:
            if vehicle.vehicle_type.is_vehicle and vehicle.lane in counts:
                counts[vehicle.lane] += 1
        return counts

    @staticmethod
    def _build_lane_statistics(vehicles: Iterable[DetectedVehicle]) -> dict[LaneDirection, LaneStatistics]:
        """Per-approach queue length in both vehicles and capacity-weighted units."""
        stats = {lane: LaneStatistics(lane=lane) for lane in APPROACH_DIRECTIONS}
        speed_totals: dict[LaneDirection, list[float]] = defaultdict(list)

        for vehicle in vehicles:
            if vehicle.lane not in stats:
                continue
            entry = stats[vehicle.lane]

            if vehicle.vehicle_type == VehicleType.PEDESTRIAN:
                entry.pedestrians_waiting += 1
                continue

            entry.vehicle_count += 1
            entry.passenger_car_units += vehicle.passenger_car_units
            if vehicle.is_emergency:
                entry.emergency_vehicles += 1
            if vehicle.speed_kph is not None:
                speed_totals[vehicle.lane].append(vehicle.speed_kph)

        for lane, speeds in speed_totals.items():
            if speeds:
                stats[lane].average_speed_kph = round(sum(speeds) / len(speeds), 1)

        for entry in stats.values():
            entry.passenger_car_units = round(entry.passenger_car_units, 2)

        return stats

    def _build_result(
        self,
        vehicles: list[DetectedVehicle],
        processing_time: float,
        source: str,
        image_path: str | None = None,
        annotated_image_path: str | None = None,
    ) -> VehicleDetectionResult:
        road_vehicles = [v for v in vehicles if v.vehicle_type.is_vehicle]
        pedestrians = [v for v in vehicles if v.vehicle_type == VehicleType.PEDESTRIAN]

        return VehicleDetectionResult(
            detection_id=str(uuid.uuid4()),
            total_vehicles=len(road_vehicles),
            lane_counts=self._count_by_lane(vehicles),
            lane_statistics=self._build_lane_statistics(vehicles),
            detected_vehicles=vehicles,
            pedestrian_count=len(pedestrians),
            processing_time=round(processing_time, 4),
            source=source,
            image_path=image_path,
            annotated_image_path=annotated_image_path,
            has_emergency_vehicles=any(v.is_emergency for v in vehicles),
        )

    def _record_metrics(self, result: VehicleDetectionResult, source: str) -> None:
        metrics.record_detection(
            source=source,
            duration=result.processing_time,
            vehicle_count=result.total_vehicles,
            confidences=[v.confidence for v in result.detected_vehicles],
        )

        self.performance_metrics["total_detections"] += 1
        self.performance_metrics["total_frames"] += 1
        self.performance_metrics["last_detection_at"] = result.detection_timestamp.isoformat()

        total = self.performance_metrics["total_detections"]
        previous_average = self.performance_metrics["average_inference_time"]
        self.performance_metrics["average_inference_time"] = round(
            (previous_average * (total - 1) + result.processing_time) / total, 4
        )

    # --- annotation ----------------------------------------------------------
    def _write_annotated_image(
        self, image: np.ndarray, vehicles: list[DetectedVehicle], original_path: str
    ) -> str | None:
        """Draw boxes and labels, and save alongside the other outputs.

        Drawn with OpenCV rather than PIL so there is no round-trip conversion
        and no dependency on a system font being installed.
        """
        try:
            canvas = image.copy()
            for vehicle in vehicles:
                box = vehicle.bounding_box
                colour = _ANNOTATION_COLOURS.get(vehicle.vehicle_type, (200, 200, 200))
                cv2.rectangle(canvas, (box.x1, box.y1), (box.x2, box.y2), colour, 2)

                label = f"{vehicle.vehicle_type.value} {vehicle.confidence:.2f}"
                if vehicle.track_id is not None:
                    label = f"#{vehicle.track_id} {label}"

                (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                # Keep the label inside the frame when the box hugs the top edge.
                label_bottom = box.y1 - 4 if box.y1 > text_height + 8 else box.y2 + text_height + 8
                label_top = label_bottom - text_height - baseline - 2

                cv2.rectangle(
                    canvas,
                    (box.x1, max(label_top, 0)),
                    (box.x1 + text_width + 6, max(label_bottom, text_height)),
                    colour,
                    -1,
                )
                cv2.putText(
                    canvas,
                    label,
                    (box.x1 + 3, max(label_bottom - baseline, text_height)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

            output_directory = Path("./output_images")
            output_directory.mkdir(parents=True, exist_ok=True)
            output_path = output_directory / f"{Path(original_path).stem}_annotated.jpg"
            cv2.imwrite(str(output_path), canvas)
            return str(output_path)
        except (cv2.error, OSError) as error:
            # A failed annotation must not fail the detection itself.
            self.log_error_with_context(error, "write_annotated_image")
            return None

    def get_performance_metrics(self) -> dict[str, Any]:
        return dict(self.performance_metrics)
