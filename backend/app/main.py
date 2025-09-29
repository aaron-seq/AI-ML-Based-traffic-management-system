"""
AI Traffic Management System - FastAPI Backend
Modern web API with real-time vehicle detection and traffic optimization
"""

from fastapi import FastAPI, File, UploadFile, WebSocket, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List
import uuid
from datetime import datetime

from app.services.intelligent_vehicle_detector import IntelligentVehicleDetector
from app.services.adaptive_traffic_manager import AdaptiveTrafficManager
from app.services.analytics_service import TrafficAnalyticsService
from app.models.traffic_models import (
    TrafficSnapshot,
    IntersectionStatus,
    VehicleDetectionResult,
    EmergencyAlert
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="AI Traffic Management System",
    description="Intelligent traffic control with real-time vehicle detection",
    version="2.0.0"
)

# Enable CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
vehicle_detector = IntelligentVehicleDetector()
traffic_manager = AdaptiveTrafficManager()
analytics_service = TrafficAnalyticsService()

# WebSocket connections for real-time updates
active_connections: List[WebSocket] = []

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("🚀 Starting AI Traffic Management System")
    await vehicle_detector.initialize()
    await analytics_service.initialize()

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down AI Traffic Management System")

# --- WebSocket for Real-time Updates ---
@app.websocket("/ws/traffic-updates")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time traffic updates"""
    await websocket.accept()
    active_connections.append(websocket)
    
    try:
        while True:
            # Send periodic updates
            intersection_status = await traffic_manager.get_current_status()
            await websocket.send_json(intersection_status.dict())
            await asyncio.sleep(1)  # Update every second
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        active_connections.remove(websocket)

# --- API Endpoints ---
@app.post("/api/detect-vehicles", response_model=VehicleDetectionResult)
async def detect_vehicles_endpoint(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...)
):
    """
    Analyze traffic image and detect vehicles using YOLOv8
    """
    try:
        # Save uploaded image temporarily
        image_id = str(uuid.uuid4())
        temp_path = f"/tmp/traffic_{image_id}.jpg"
        
        contents = await image.read()
        with open(temp_path, "wb") as f:
            f.write(contents)
        
        # Perform vehicle detection
        detection_result = await vehicle_detector.analyze_intersection_image(temp_path)
        
        # Update traffic management system
        await traffic_manager.update_vehicle_counts(detection_result.lane_counts)
        
        # Store analytics data
        background_tasks.add_task(
            analytics_service.record_detection,
            detection_result,
            datetime.utcnow()
        )
        
        # Broadcast updates to connected clients
        await broadcast_update({
            "type": "vehicle_detection",
            "data": detection_result.dict()
        })
        
        return detection_result
        
    except Exception as e:
        logger.error(f"Vehicle detection error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Vehicle detection failed"}
        )

@app.get("/api/intersection-status", response_model=IntersectionStatus)
async def get_intersection_status():
    """Get current intersection status and signal states"""
    return await traffic_manager.get_current_status()

@app.post("/api/emergency-override")
async def emergency_override(alert: EmergencyAlert):
    """Handle emergency vehicle detection and override signals"""
    try:
        await traffic_manager.handle_emergency_override(alert)
        
        await broadcast_update({
            "type": "emergency_alert",
            "data": alert.dict()
        })
        
        return {"status": "emergency_override_activated", "alert_id": alert.id}
        
    except Exception as e:
        logger.error(f"Emergency override error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Emergency override failed"}
        )

@app.get("/api/analytics/summary")
async def get_traffic_analytics():
    """Get traffic analytics and performance metrics"""
    try:
        analytics = await analytics_service.generate_summary()
        return analytics
    except Exception as e:
        logger.error(f"Analytics error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Analytics unavailable"}
        )

@app.get("/api/simulation/start")
async def start_simulation():
    """Start the traffic simulation with current parameters"""
    try:
        await traffic_manager.start_simulation()
        return {"status": "simulation_started"}
    except Exception as e:
        logger.error(f"Simulation start error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to start simulation"}
        )

@app.post("/api/simulation/configure")
async def configure_simulation(config: Dict):
    """Configure simulation parameters"""
    try:
        await traffic_manager.update_configuration(config)
        return {"status": "configuration_updated"}
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Configuration update failed"}
        )

# --- Utility Functions ---
async def broadcast_update(message: Dict):
    """Broadcast updates to all connected WebSocket clients"""
    disconnected = []
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except:
            disconnected.append(connection)
    
    # Remove disconnected clients
    for conn in disconnected:
        active_connections.remove(conn)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "vehicle_detector": vehicle_detector.is_ready(),
            "traffic_manager": traffic_manager.is_ready(),
            "analytics": analytics_service.is_ready()
        }
    }

# Serve static files (for demo images, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
