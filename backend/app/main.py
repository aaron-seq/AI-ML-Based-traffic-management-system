"""
AI Traffic Management System - Modern FastAPI Backend
High-performance web API with real-time vehicle detection and traffic optimization
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from fastapi import (
    FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect,
    BackgroundTasks, HTTPException, Depends, status
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from .core.config import settings
from .core.logger import setup_logging, get_application_logger
from .services.intelligent_vehicle_detector import IntelligentVehicleDetector
from .services.adaptive_traffic_manager import AdaptiveTrafficManager
from .services.analytics_service import TrafficAnalyticsService
from .models.traffic_models import (
    VehicleDetectionResult, IntersectionStatus, 
    EmergencyAlert, TrafficSnapshot, SystemHealthStatus
)

# Initialize logging
setup_logging()
logger = get_application_logger("main")

# Global services - will be initialized in lifespan
vehicle_detector: IntelligentVehicleDetector = None
traffic_manager: AdaptiveTrafficManager = None
analytics_service: TrafficAnalyticsService = None

# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

websocket_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("Starting AI Traffic Management System")
    
    try:
        # Initialize services
        global vehicle_detector, traffic_manager, analytics_service
        
        vehicle_detector = IntelligentVehicleDetector()
        traffic_manager = AdaptiveTrafficManager()
        analytics_service = TrafficAnalyticsService()
        
        # Initialize services
        await vehicle_detector.initialize()
        await analytics_service.initialize()
        await traffic_manager.start_simulation()
        
        # Create necessary directories
        Path("./output_images").mkdir(exist_ok=True)
        Path("./uploads").mkdir(exist_ok=True)
        Path("./logs").mkdir(exist_ok=True)
        
        logger.info("All services initialized successfully")
        
    except Exception as error:
        logger.error(f"Failed to initialize services: {error}")
        raise
    
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

# Middleware
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


# Dependency functions
async def get_vehicle_detector() -> IntelligentVehicleDetector:
    """Get vehicle detector dependency"""
    if not vehicle_detector or not vehicle_detector.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vehicle detection service not available"
        )
    return vehicle_detector


async def get_traffic_manager() -> AdaptiveTrafficManager:
    """Get traffic manager dependency"""
    if not traffic_manager or not traffic_manager.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffic management service not available"
        )
    return traffic_manager


async def get_analytics_service() -> TrafficAnalyticsService:
    """Get analytics service dependency"""
    if not analytics_service or not analytics_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics service not available"
        )
    return analytics_service


# WebSocket endpoint for real-time updates
@app.websocket("/ws/traffic-updates")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time traffic updates"""
    await websocket_manager.connect(websocket)
    
    try:
        while True:
            # Send periodic updates
            if traffic_manager and traffic_manager.is_ready():
                intersection_status = await traffic_manager.get_current_status()
                await websocket.send_json({
                    "type": "intersection_status",
                    "data": intersection_status.dict(),
                    "timestamp": datetime.utcnow().isoformat()
                })
            
            await asyncio.sleep(2)  # Update every 2 seconds
            
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
    except Exception as error:
        logger.error(f"WebSocket error: {error}")
        websocket_manager.disconnect(websocket)


# API Routes
@app.post("/api/detect-vehicles", response_model=VehicleDetectionResult)
async def detect_vehicles_endpoint(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    detector: IntelligentVehicleDetector = Depends(get_vehicle_detector),
    manager: AdaptiveTrafficManager = Depends(get_traffic_manager),
    analytics: TrafficAnalyticsService = Depends(get_analytics_service)
):
    """Analyze traffic image and detect vehicles using YOLOv8"""
    try:
        # Validate file type
        if not image.content_type.startswith('image/'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be an image"
            )
        
        # Save uploaded image temporarily
        upload_id = str(uuid.uuid4())
        temp_path = f"./uploads/traffic_{upload_id}.jpg"
        
        contents = await image.read()
        with open(temp_path, "wb") as f:
            f.write(contents)
        
        logger.info(f"Processing uploaded image: {image.filename}")
        
        # Perform vehicle detection
        detection_result = await detector.analyze_intersection_image(
            temp_path, save_annotated=True
        )
        
        # Update traffic management system
        await manager.update_vehicle_counts(detection_result.lane_counts)
        
        # Record analytics data
        background_tasks.add_task(
            analytics.record_detection,
            detection_result,
            datetime.utcnow()
        )
        
        # Broadcast updates to WebSocket clients
        background_tasks.add_task(
            websocket_manager.broadcast,
            {
                "type": "vehicle_detection",
                "data": detection_result.dict(),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        # Clean up temporary file
        background_tasks.add_task(
            lambda: Path(temp_path).unlink(missing_ok=True)
        )
        
        logger.info(
            f"Vehicle detection completed: {detection_result.total_vehicles} vehicles detected"
        )
        
        return detection_result
        
    except Exception as error:
        logger.error(f"Vehicle detection error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vehicle detection failed: {str(error)}"
        )


@app.get("/api/intersection-status", response_model=IntersectionStatus)
async def get_intersection_status(
    manager: AdaptiveTrafficManager = Depends(get_traffic_manager)
):
    """Get current intersection status and signal states"""
    return await manager.get_current_status()


@app.post("/api/emergency-override")
async def emergency_override(
    alert: EmergencyAlert,
    background_tasks: BackgroundTasks,
    manager: AdaptiveTrafficManager = Depends(get_traffic_manager)
):
    """Handle emergency vehicle detection and override signals"""
    try:
        await manager.handle_emergency_override(alert)
        
        # Broadcast emergency alert
        background_tasks.add_task(
            websocket_manager.broadcast,
            {
                "type": "emergency_alert",
                "data": alert.dict(),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        logger.warning(f"Emergency override activated: {alert.alert_id}")
        
        return {
            "status": "emergency_override_activated",
            "alert_id": alert.alert_id,
            "message": f"Emergency override activated for {alert.detected_lane.value} lane"
        }
        
    except Exception as error:
        logger.error(f"Emergency override error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Emergency override failed: {str(error)}"
        )


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


@app.get("/api/analytics/heatmap")
async def get_traffic_heatmap(
    hours: int = 24,
    analytics: TrafficAnalyticsService = Depends(get_analytics_service)
):
    """Get traffic heatmap data for visualization"""
    try:
        return await analytics.get_traffic_heatmap_data(hours)
    except Exception as error:
        logger.error(f"Heatmap generation error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Heatmap data unavailable: {str(error)}"
        )


@app.get("/api/analytics/performance")
async def get_performance_report(
    analytics: TrafficAnalyticsService = Depends(get_analytics_service)
):
    """Get detailed performance report"""
    try:
        return await analytics.get_performance_report()
    except Exception as error:
        logger.error(f"Performance report error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Performance report unavailable: {str(error)}"
        )


@app.post("/api/simulation/start")
async def start_simulation(
    manager: AdaptiveTrafficManager = Depends(get_traffic_manager)
):
    """Start the traffic simulation"""
    try:
        await manager.start_simulation()
        logger.info("Traffic simulation started")
        return {"status": "simulation_started", "message": "Traffic simulation is now running"}
    except Exception as error:
        logger.error(f"Simulation start error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start simulation: {str(error)}"
        )


@app.post("/api/simulation/stop")
async def stop_simulation(
    manager: AdaptiveTrafficManager = Depends(get_traffic_manager)
):
    """Stop the traffic simulation"""
    try:
        await manager.stop_simulation()
        logger.info("Traffic simulation stopped")
        return {"status": "simulation_stopped", "message": "Traffic simulation has been stopped"}
    except Exception as error:
        logger.error(f"Simulation stop error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop simulation: {str(error)}"
        )


@app.post("/api/configuration")
async def update_configuration(
    config: Dict,
    manager: AdaptiveTrafficManager = Depends(get_traffic_manager)
):
    """Update system configuration"""
    try:
        await manager.update_configuration(config)
        logger.info(f"Configuration updated: {config}")
        return {
            "status": "configuration_updated",
            "message": "System configuration has been updated",
            "updated_config": config
        }
    except Exception as error:
        logger.error(f"Configuration update error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Configuration update failed: {str(error)}"
        )


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint"""
    try:
        health_status = SystemHealthStatus(
            system_uptime=(datetime.utcnow() - datetime.utcnow()).total_seconds(),  # Will be properly calculated
            cpu_usage=25.0,  # Placeholder
            memory_usage=45.0,  # Placeholder
            detection_model_status=vehicle_detector.is_ready() if vehicle_detector else False,
            database_status=True,  # Placeholder
            api_status=True,
            websocket_connections=len(websocket_manager.active_connections),
            average_response_time=0.15  # Placeholder
        )
        
        return {
            "status": "healthy" if health_status.is_healthy() else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "health_score": health_status.get_health_score(),
            "services": {
                "vehicle_detector": vehicle_detector.is_ready() if vehicle_detector else False,
                "traffic_manager": traffic_manager.is_ready() if traffic_manager else False,
                "analytics": analytics_service.is_ready() if analytics_service else False
            },
            "websocket_connections": len(websocket_manager.active_connections),
            "version": settings.application_version
        }
    except Exception as error:
        logger.error(f"Health check error: {error}")
        return {
            "status": "unhealthy",
            "error": str(error),
            "timestamp": datetime.utcnow().isoformat()
        }


@app.get("/api/system/info")
async def get_system_info():
    """Get system information"""
    return {
        "application_name": settings.application_name,
        "version": settings.application_version,
        "environment": "development" if settings.debug_mode else "production",
        "api_prefix": settings.api_prefix,
        "features": {
            "vehicle_detection": True,
            "adaptive_signals": True,
            "emergency_override": True,
            "real_time_analytics": True,
            "websocket_support": True
        }
    }


# Serve static files for annotated images
app.mount("/static", StaticFiles(directory="output_images"), name="static")


# Custom exception handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"detail": "Endpoint not found", "path": str(request.url.path)}
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    logger.error(f"Internal server error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_id": str(uuid.uuid4())}
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