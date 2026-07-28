"""Detection endpoints: analyse images, videos and streams."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status

from ...core import metrics
from ...core.config import settings
from ...core.events import event_bus
from ...core.logger import get_application_logger
from ...core.security import file_extension, generate_secure_filename, looks_like_image
from ...models.traffic_models import VehicleDetectionResult, VideoAnalysisResult
from ...services.intelligent_vehicle_detector import DetectorNotReadyError, UnreadableMediaError
from ..deps import (
    AnalyticsDep,
    DetectorDep,
    ForecastDep,
    NetworkDep,
    upload_rate_limit,
    verify_write_access,
)

logger = get_application_logger("api.detection")

router = APIRouter(
    prefix="/detection",
    tags=["detection"],
    dependencies=[Depends(upload_rate_limit), Depends(verify_write_access)],
)

UPLOAD_DIRECTORY = Path("./uploads")


async def _store_upload(upload: UploadFile, allowed_extensions: list[str], require_image_magic: bool) -> Path:
    """Validate and persist an upload, returning the path it was written to.

    The body is streamed in bounded chunks and aborted the moment it exceeds the
    limit, so an oversized upload cannot exhaust memory before being rejected.
    """
    extension = file_extension(upload.filename)
    if extension not in {ext.lower() for ext in allowed_extensions}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type {extension or '(none)'}. Allowed: {', '.join(allowed_extensions)}",
        )

    UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIRECTORY / generate_secure_filename(upload.filename)

    limit = settings.max_upload_size_bytes
    written = 0
    first_chunk = b""

    try:
        with destination.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                if not first_chunk:
                    first_chunk = chunk[:32]
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"File exceeds the {settings.max_upload_size_mb} MB limit.",
                    )
                handle.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=f"Could not write the upload to disk: {error}",
        ) from error

    if written == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file is empty.")

    # Trusting the extension alone would let a renamed executable through.
    if require_image_magic and not looks_like_image(first_chunk):
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File content does not match a supported image format.",
        )

    return destination


@router.post(
    "/image",
    response_model=VehicleDetectionResult,
    summary="Detect vehicles and pedestrians in an image",
)
async def detect_in_image(
    background_tasks: BackgroundTasks,
    detector: DetectorDep,
    network: NetworkDep,
    analytics: AnalyticsDep,
    forecast: ForecastDep,
    image: Annotated[UploadFile, File(description="JPEG, PNG, BMP or WebP image of an intersection")],
    intersection_id: Annotated[
        str, Query(description="Intersection to update with the resulting counts")
    ] = "main_intersection",
    save_annotated: Annotated[bool, Query(description="Write an annotated copy to ./output_images")] = True,
    confidence: Annotated[
        float | None, Query(ge=0.0, le=1.0, description="Override the confidence threshold")
    ] = None,
    update_signals: Annotated[bool, Query(description="Feed the counts into the signal controller")] = True,
) -> VehicleDetectionResult:
    """Analyse a still image and, by default, drive the signals from the result."""
    stored_path = await _store_upload(image, settings.allowed_image_types, require_image_magic=True)

    try:
        result = await detector.analyze_intersection_image(
            str(stored_path), save_annotated=save_annotated, confidence=confidence
        )
    except UnreadableMediaError as error:
        stored_path.unlink(missing_ok=True)
        metrics.record_detection_failure("image")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except DetectorNotReadyError as error:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except Exception as error:
        stored_path.unlink(missing_ok=True)
        metrics.record_detection_failure("image")
        logger.error("Image detection failed: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Detection failed. See server logs."
        ) from error

    if update_signals and network.exists(intersection_id):
        await network.update_counts(intersection_id, result.lane_counts, result.lane_statistics)

    forecast.record_observation(intersection_id, result.lane_counts, result.detection_timestamp)

    background_tasks.add_task(analytics.record_detection, result, result.detection_timestamp, intersection_id)
    background_tasks.add_task(event_bus.publish, "vehicle_detection", result.model_dump(mode="json"))
    background_tasks.add_task(stored_path.unlink, True)

    return result


@router.post(
    "/video",
    response_model=VideoAnalysisResult,
    summary="Analyse a video with object tracking",
)
async def detect_in_video(
    detector: DetectorDep,
    network: NetworkDep,
    forecast: ForecastDep,
    background_tasks: BackgroundTasks,
    video: Annotated[UploadFile, File(description="MP4, AVI, MOV, MKV or WebM clip")],
    intersection_id: Annotated[str, Query()] = "main_intersection",
    frame_stride: Annotated[int | None, Query(ge=1, le=30, description="Analyse every Nth frame")] = None,
    max_frames: Annotated[int | None, Query(ge=1, le=10_000)] = None,
    metres_per_pixel: Annotated[
        float | None,
        Query(gt=0, description="Ground sampling distance; required for speed estimates"),
    ] = None,
    include_frames: Annotated[bool, Query(description="Include per-frame detail (large response)")] = False,
    update_signals: Annotated[bool, Query()] = True,
) -> VideoAnalysisResult:
    """Track road users across a clip to get unique counts, flow rate and speeds.

    Tracking is what separates this from repeated single-image detection: the
    same car in 30 frames is one vehicle, not thirty.
    """
    stored_path = await _store_upload(video, settings.allowed_video_types, require_image_magic=False)

    try:
        result = await detector.analyze_video(
            str(stored_path),
            frame_stride=frame_stride,
            max_frames=max_frames,
            metres_per_pixel=metres_per_pixel,
            keep_frame_results=include_frames,
        )
    except UnreadableMediaError as error:
        stored_path.unlink(missing_ok=True)
        metrics.record_detection_failure("video")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except DetectorNotReadyError as error:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except Exception as error:
        stored_path.unlink(missing_ok=True)
        metrics.record_detection_failure("video")
        logger.error("Video analysis failed: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video analysis failed. See server logs.",
        ) from error

    if update_signals and network.exists(intersection_id):
        await network.update_counts(intersection_id, result.lane_counts)

    forecast.record_observation(intersection_id, result.lane_counts, result.analysed_at)

    background_tasks.add_task(event_bus.publish, "video_analysis", result.model_dump(mode="json"))
    background_tasks.add_task(stored_path.unlink, True)

    return result


@router.post(
    "/stream",
    response_model=VideoAnalysisResult,
    summary="Sample a live camera stream",
)
async def detect_in_stream(
    detector: DetectorDep,
    network: NetworkDep,
    forecast: ForecastDep,
    stream_url: Annotated[str, Query(description="RTSP or HTTP(S) stream URL")],
    intersection_id: Annotated[str, Query()] = "main_intersection",
    max_frames: Annotated[int, Query(ge=1, le=600)] = 60,
    frame_stride: Annotated[int, Query(ge=1, le=30)] = 2,
    metres_per_pixel: Annotated[float | None, Query(gt=0)] = None,
    update_signals: Annotated[bool, Query()] = True,
) -> VideoAnalysisResult:
    """Pull a bounded sample of frames from a live camera and analyse them.

    Poll this endpoint on a schedule to keep an intersection continuously fed
    from a fixed camera. It samples a bounded number of frames and returns, so
    it never holds the connection open indefinitely.
    """
    if not stream_url.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stream_url must be an rtsp://, rtsps://, http:// or https:// URL.",
        )

    try:
        result = await detector.analyze_video(
            stream_url,
            frame_stride=frame_stride,
            max_frames=max_frames,
            metres_per_pixel=metres_per_pixel,
            keep_frame_results=False,
        )
    except UnreadableMediaError as error:
        metrics.record_detection_failure("stream")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not read the stream: {error}",
        ) from error
    except Exception as error:
        metrics.record_detection_failure("stream")
        logger.error("Stream analysis failed: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stream analysis failed. See server logs.",
        ) from error

    if update_signals and network.exists(intersection_id):
        await network.update_counts(intersection_id, result.lane_counts)

    forecast.record_observation(intersection_id, result.lane_counts, result.analysed_at)
    event_bus.publish("stream_analysis", result.model_dump(mode="json"))
    return result


@router.get("/performance", summary="Detection pipeline statistics")
async def detection_performance(detector: DetectorDep) -> dict[str, object]:
    """Throughput and latency of the detection model."""
    return {
        "model": settings.model_name,
        "device": settings.inference_device,
        "confidence_threshold": settings.detection_confidence_threshold,
        "image_size": settings.detection_image_size,
        **detector.get_performance_metrics(),
    }
