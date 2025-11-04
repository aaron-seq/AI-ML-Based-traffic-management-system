"""
API router for the AI Traffic Management System
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from starlette.responses import PlainTextResponse
from ..models.traffic_models import SystemHealthStatus, IntersectionStatus, EmergencyAlert
from ..core.config import settings

router = APIRouter()

@router.get("/health", response_model=SystemHealthStatus)
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "uptime": 0.0,
        "cpu_usage": 0.0,
        "memory_usage": 0.0,
        "services": {
            "vehicle_detector": True,
            "traffic_manager": True,
            "analytics_service": True,
        },
    }

@router.get("/system/info")
async def system_info():
    """System information endpoint"""
    return {
        "application_name": settings.application_name,
        "version": settings.application_version,
    }

@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint"""
    return ""

@router.get("/intersection-status", response_model=IntersectionStatus)
async def intersection_status():
    """Intersection status endpoint"""
    return {
        "signals": {},
        "vehicle_counts": {},
        "emergency_mode_active": False,
    }

@router.post("/detect-vehicles")
async def detect_vehicles(image: UploadFile = File(...)):
    """Vehicle detection endpoint"""
    if image.content_type not in ["image/jpeg", "image/png"]:
        raise HTTPException(status_code=400, detail="Invalid file type")
    return {}

@router.post("/emergency-override")
async def emergency_override(alert: EmergencyAlert):
    """Emergency override endpoint"""
    return {}
