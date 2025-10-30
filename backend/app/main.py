"""AI Traffic Management System - Modern FastAPI Backend
High-performance web API with real-time vehicle detection and traffic optimization
"""

import asyncio
import uuid
import psutil
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import (
    FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect,
    BackgroundTasks, HTTPException, Depends, status, Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

# Import core modules
from .core.config import settings
from .core.logger import setup_logging, get_application_logger
from .core.metrics import get_metrics_response, track_emergency_override, update_websocket_connections
from .core.security import SecurityManager, check_rate_limit, sanitize_filename, validate_file_type

# Import middleware
from .middleware import SecurityMiddleware, MetricsMiddleware, RequestLoggingMiddleware, HealthCheckMiddleware

# Import services with error handling
try:
    from .services.intelligent_vehicle_detector import IntelligentVehicleDetector
    from .services.adaptive_traffic_manager import AdaptiveTrafficManager
    from .services.analytics_service import TrafficAnalyticsService
except ImportError as e:
    # Log import error but continue - services will be None
    print(f"Warning: Could not import services: {e}")
    IntelligentVehicleDetector = None
    AdaptiveTrafficManager = None 
    TrafficAnalyticsService = None

# Import models with error handling
try:
    from .models.traffic_models import (
        VehicleDetectionResult, IntersectionStatus, 
        EmergencyAlert, TrafficSnapshot, SystemHealthStatus
    )
except ImportError as e:
    print(f"Warning: Could not import models: {e}")
    # Create placeholder classes
    class VehicleDetectionResult: pass
    class IntersectionStatus: pass
    class EmergencyAlert: pass
    class TrafficSnapshot: pass
    class SystemHealthStatus: pass

# Initialize logging
setup_logging()
logger = get_application_logger("main")

# Global services - will be initialized in lifespan
vehicle_detector: Optional[IntelligentVehicleDetector] = None
traffic_manager: Optional[AdaptiveTrafficManager] = None
analytics_service: Optional[TrafficAnalyticsService] = None
security_manager = SecurityManager()

# Application start time for uptime calculation
app_start_time = time.time()


class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        update_websocket_connections(len(self.active_connections))
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        update_websocket_connections(len(self.active_connections))
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: str, websocket: WebSocket):
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {e}")
            self.disconnect(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket broadcast error: {e}")
                disconnected.append(connection)
        
        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn)


websocket_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management with comprehensive error handling"""
    # Startup
    logger.info("Starting AI Traffic Management System")
    
    try:
        # Initialize services if available
        global vehicle_detector, traffic_manager, analytics_service
        
        if IntelligentVehicleDetector:
            try:
                vehicle_detector = IntelligentVehicleDetector()
                await vehicle_detector.initialize()
                logger.info("Vehicle detector initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize vehicle detector: {e}")
                vehicle_detector = None
        
        if AdaptiveTrafficManager:
            try:
                traffic_manager = AdaptiveTrafficManager()
                await traffic_manager.initialize()
                logger.info("Traffic manager initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize traffic manager: {e}")
                traffic_manager = None
        
        if TrafficAnalyticsService:
            try:
                analytics_service = TrafficAnalyticsService()
                await analytics_service.initialize()
                logger.info("Analytics service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize analytics service: {e}")
                analytics_service = None
        
        # Start simulation if traffic manager is available
        if traffic_manager:
            try:
                await traffic_manager.start_simulation()
                logger.info("Traffic simulation started")
            except Exception as e:
                logger.error(f"Failed to start simulation: {e}")
        
        # Create necessary directories
        directories = ["./output_images", "./uploads", "./logs", "./models"]
        for directory in directories:
            Path(directory).mkdir(exist_ok=True)
        
        logger.info("Application startup completed")
        
    except Exception as error:
        logger.error(f"Critical startup error: {error}")
        # Continue startup even if some services fail
    
    yield
    
    # Shutdown
    logger.info("Shutting down AI Traffic Management System")
    
    try:
        if traffic_manager:
            await traffic_manager.cleanup()
        if vehicle_detector:
            await vehicle_detector.cleanup()
        if analytics_service:
            await analytics_service.cleanup()
            
        logger.info("All services shut down successfully")
        
    except Exception as error:
        logger.error(f"Error during shutdown: {error}")


# Create FastAPI application
app = FastAPI(
    title=settings.application_name,
    description="Intelligent traffic control with real-time vehicle detection and adaptive signal optimization",
    version=settings.application_version,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug_mode else None,
    redoc_url="/api/redoc" if settings.debug_mode else None
)

# Security
security = HTTPBearer(auto_error=False)

# Add middleware in correct order (reverse order of execution)
app.add_middleware(HealthCheckMiddleware)
app.add_middleware(SecurityMiddleware)
app.add_middleware(MetricsMiddleware)
if settings.debug_mode:
    app.add_middleware(RequestLoggingMiddleware, log_body=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=settings.allowed_methods,
    allow_headers=settings.allowed_headers,
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"] if settings.debug_mode else ["localhost", "127.0.0.1"]
)


# Dependency functions with improved error handling
async def get_vehicle_detector() -> Optional[IntelligentVehicleDetector]:
    """Get vehicle detector dependency"""
    if not vehicle_detector:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vehicle detection service not available"
        )
    
    if not vehicle_detector.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vehicle detection service not ready"
        )
    return vehicle_detector


async def get_traffic_manager() -> Optional[AdaptiveTrafficManager]:
    """Get traffic manager dependency"""
    if not traffic_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffic management service not available"
        )
    
    if not traffic_manager.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffic management service not ready"
        )
    return traffic_manager


async def get_analytics_service() -> Optional[TrafficAnalyticsService]:
    """Get analytics service dependency"""
    if not analytics_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics service not available"
        )
    
    if not analytics_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics service not ready"
        )
    return analytics_service


# Metrics endpoint
@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics endpoint"""
    return get_metrics_response()


# WebSocket endpoint for real-time updates
@app.websocket("/ws/traffic-updates")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time traffic updates"""
    await websocket_manager.connect(websocket)
    
    try:
        while True:
            # Send periodic updates
            if traffic_manager and traffic_manager.is_ready():
                try:
                    intersection_status = await traffic_manager.get_current_status()
                    await websocket.send_json({
                        "type": "intersection_status",
                        "data": intersection_status.dict() if hasattr(intersection_status, 'dict') else str(intersection_status),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                except Exception as e:
                    logger.error(f"WebSocket data error: {e}")
            
            await asyncio.sleep(2)  # Update every 2 seconds
            
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
    except Exception as error:
        logger.error(f"WebSocket error: {error}")
        websocket_manager.disconnect(websocket)


# API Routes
@app.post("/api/detect-vehicles")
async def detect_vehicles_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    detector: IntelligentVehicleDetector = Depends(get_vehicle_detector),
    manager: AdaptiveTrafficManager = Depends(get_traffic_manager),
    analytics: TrafficAnalyticsService = Depends(get_analytics_service)
):
    """Analyze traffic image and detect vehicles using YOLOv8"""
    try:
        # Rate limiting is handled by middleware
        
        # Validate file type and size
        if not image.content_type or not image.content_type.startswith('image/'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be an image (JPEG, PNG, etc.)"
            )
        
        # Check file size (10MB limit)
        contents = await image.read()
        if len(contents) > 10 * 1024 * 1024:  # 10MB
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File size too large (max 10MB)"
            )
        
        # Validate file type by extension
        if not validate_file_type(image.filename, ['.jpg', '.jpeg', '.png', '.bmp']):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file type. Use JPEG, PNG, or BMP."
            )
        
        # Generate secure filename
        secure_filename = sanitize_filename(image.filename or "upload.jpg")
        upload_id = str(uuid.uuid4())
        temp_path = f"./uploads/traffic_{upload_id}_{secure_filename}"
        
        # Save uploaded image
        with open(temp_path, "wb") as f:
            f.write(contents)
        
        logger.info(f"Processing uploaded image: {image.filename} -> {temp_path}")
        
        # Perform vehicle detection
        detection_result = await detector.analyze_intersection_image(
            temp_path, save_annotated=True
        )
        
        # Update traffic management system
        if hasattr(detection_result, 'lane_counts'):
            await manager.update_vehicle_counts(detection_result.lane_counts)
        
        # Record analytics data
        if analytics:
            background_tasks.add_task(
                analytics.record_detection,
                detection_result,
                datetime.now(timezone.utc)
            )
        
        # Broadcast updates to WebSocket clients
        background_tasks.add_task(
            websocket_manager.broadcast,
            {
                "type": "vehicle_detection",
                "data": detection_result.dict() if hasattr(detection_result, 'dict') else str(detection_result),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        
        # Clean up temporary file
        background_tasks.add_task(
            lambda: Path(temp_path).unlink(missing_ok=True)
        )
        
        total_vehicles = getattr(detection_result, 'total_vehicles', 0)
        logger.info(f"Vehicle detection completed: {total_vehicles} vehicles detected")
        
        return detection_result
        
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Vehicle detection error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vehicle detection failed: {str(error)}"
        )


@app.get("/api/intersection-status")
async def get_intersection_status(
    manager: AdaptiveTrafficManager = Depends(get_traffic_manager)
):
    """Get current intersection status and signal states"""
    try:
        return await manager.get_current_status()
    except Exception as error:
        logger.error(f"Intersection status error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get intersection status: {str(error)}"
        )


@app.post("/api/emergency-override")
async def emergency_override(
    alert: dict,  # Use dict instead of EmergencyAlert to avoid import issues
    background_tasks: BackgroundTasks,
    manager: AdaptiveTrafficManager = Depends(get_traffic_manager)
):
    """Handle emergency vehicle detection and override signals"""
    try:
        # Validate required fields
        required_fields = ['alert_id', 'emergency_type', 'detected_lane']
        for field in required_fields:
            if field not in alert:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required field: {field}"
                )
        
        await manager.handle_emergency_override(alert)
        
        # Track emergency override metrics
        track_emergency_override(
            alert.get('emergency_type', 'unknown'),
            alert.get('detected_lane', 'unknown')
        )
        
        # Broadcast emergency alert
        background_tasks.add_task(
            websocket_manager.broadcast,
            {
                "type": "emergency_alert",
                "data": alert,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        
        logger.warning(f"Emergency override activated: {alert.get('alert_id')}")
        
        return {
            "status": "emergency_override_activated",
            "alert_id": alert.get('alert_id'),
            "message": f"Emergency override activated for {alert.get('detected_lane')} lane"
        }
        
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Emergency override error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Emergency override failed: {str(error)}"
        )


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint"""
    try:
        # Calculate uptime
        uptime_seconds = time.time() - app_start_time
        
        # Get system metrics
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_bytes = memory.used
        except Exception:
            cpu_percent = 0.0
            memory_percent = 0.0
            memory_bytes = 0
        
        # Check service health
        services = {
            "vehicle_detector": vehicle_detector.is_ready() if vehicle_detector else False,
            "traffic_manager": traffic_manager.is_ready() if traffic_manager else False,
            "analytics": analytics_service.is_ready() if analytics_service else False
        }
        
        # Calculate health score
        healthy_services = sum(1 for status in services.values() if status)
        total_services = len(services)
        health_score = (healthy_services / total_services) if total_services > 0 else 0.0
        
        # Determine overall status
        if health_score >= 0.8:
            overall_status = "healthy"
        elif health_score >= 0.5:
            overall_status = "degraded"
        else:
            overall_status = "unhealthy"
        
        return {
            "status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": uptime_seconds,
            "health_score": health_score,
            "services": services,
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "memory_bytes": memory_bytes
            },
            "websocket_connections": len(websocket_manager.active_connections),
            "version": settings.application_version,
            "environment": getattr(settings, 'environment', 'unknown')
        }
        
    except Exception as error:
        logger.error(f"Health check error: {error}")
        return {
            "status": "unhealthy",
            "error": str(error),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": settings.application_version
        }


@app.get("/api/system/info")
async def get_system_info():
    """Get system information"""
    return {
        "application_name": settings.application_name,
        "version": settings.application_version,
        "environment": getattr(settings, 'environment', 'development'),
        "api_prefix": settings.api_prefix,
        "debug_mode": settings.debug_mode,
        "features": {
            "vehicle_detection": vehicle_detector is not None,
            "adaptive_signals": traffic_manager is not None,
            "emergency_override": True,
            "real_time_analytics": analytics_service is not None,
            "websocket_support": True,
            "metrics_collection": True,
            "rate_limiting": True,
            "security_middleware": True
        },
        "model_info": {
            "model_name": settings.model_name,
            "confidence_threshold": settings.detection_confidence_threshold,
            "gpu_acceleration": settings.enable_gpu_acceleration
        }
    }


# Analytics endpoints (with error handling)
@app.get("/api/analytics/summary")
async def get_traffic_analytics(
    period: str = "current",
    analytics: TrafficAnalyticsService = Depends(get_analytics_service)
):
    """Get traffic analytics and performance metrics"""
    try:
        return await analytics.generate_summary(period)
    except Exception as error:
        logger.error(f"Analytics error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analytics unavailable: {str(error)}"
        )


# Serve static files for annotated images (with error handling)
try:
    if Path("./output_images").exists():
        app.mount("/static", StaticFiles(directory="output_images"), name="static")
except Exception as e:
    logger.warning(f"Could not mount static files: {e}")


# Custom exception handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"detail": "Endpoint not found", "path": str(request.url.path)}
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    error_id = str(uuid.uuid4())
    logger.error(f"Internal server error [{error_id}] on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_id": error_id}
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug_mode,
        log_level=settings.log_level.lower()
    )
