"""
Main application entry point for the AI Traffic Management System
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
import uvicorn

from .api.routes import router
from .core.config import settings
from .core.logger import get_application_logger
from .middleware.middleware import LoggingMiddleware
from .services.adaptive_traffic_manager import AdaptiveTrafficManager
from .services.analytics_service import TrafficAnalyticsService
from .services.intelligent_vehicle_detector import IntelligentVehicleDetector
from .websocket.manager import WebSocketManager


# Global service instances
vehicle_detector = IntelligentVehicleDetector()
traffic_manager = AdaptiveTrafficManager()
analytics_service = TrafficAnalyticsService()
websocket_manager = WebSocketManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles application startup and shutdown events"""
    
    logger = get_application_logger("main")
    logger.info("Starting application lifespan...")
    
    # Initialize services
    await vehicle_detector.initialize()
    await traffic_manager.initialize()
    await analytics_service.initialize()
    
    # Start WebSocket broadcasting in the background
    asyncio.create_task(
        websocket_manager.broadcast_traffic_updates(traffic_manager)
    )
    
    logger.info("Application services initialized.")
    
    yield
    
    # Cleanup services
    logger.info("Starting application shutdown...")
    
    await vehicle_detector.cleanup()
    await traffic_manager.cleanup()
    await analytics_service.cleanup()

    logger.info("Application shutdown complete.")


# FastAPI application setup
app = FastAPI(
    title=settings.application_name,
    version=settings.application_version,
    debug=settings.debug_mode,
    lifespan=lifespan
)


# Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=settings.allowed_methods,
    allow_headers=settings.allowed_headers,
)
app.add_middleware(
    LoggingMiddleware
)

# API router
app.include_router(router, prefix=settings.api_prefix)


# Default route
@app.get("/", tags=["Default"])
async def read_root():
    """Default root endpoint"""
    return {"message": "Welcome to the AI Traffic Management System"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint"""
    return ""


# Main entry point for running the application
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.log_level.lower()
    )
