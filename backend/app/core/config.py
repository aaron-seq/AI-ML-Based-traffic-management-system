"""
Configuration management for AI Traffic Management System
Handles environment variables and application settings
"""

import os
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings
from pydantic import field_validator


class ApplicationSettings(BaseSettings):
    """Application configuration with environment variable support"""

    # Application Info
    application_name: str = "AI Traffic Management System"
    application_version: str = "2.0.0"
    debug_mode: bool = False

    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api"

    # CORS Settings
    allowed_origins: List[str] = ["*"]
    allowed_methods: List[str] = ["*"]
    allowed_headers: List[str] = ["*"]

    # Database Configuration
    mongodb_connection_string: str = "mongodb://localhost:27017"
    database_name: str = "traffic_management"

    # Redis Configuration
    redis_connection_string: str = "redis://localhost:6379"
    redis_cache_ttl: int = 3600  # 1 hour

    # AI Model Configuration
    model_name: str = "yolov8n.pt"
    detection_confidence_threshold: float = 0.4
    non_max_suppression_threshold: float = 0.45
    enable_gpu_acceleration: bool = True
    model_cache_directory: str = "./models"

    # Traffic Management Settings
    default_green_signal_duration: int = 30  # seconds
    yellow_signal_duration: int = 3  # seconds
    minimum_green_duration: int = 10  # seconds
    maximum_green_duration: int = 120  # seconds

    # Emergency Response Settings
    emergency_override_duration: int = 60  # seconds
    emergency_detection_enabled: bool = True

    # Logging Configuration
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    enable_file_logging: bool = True
    log_file_path: str = "./logs/traffic_system.log"

    # Performance Settings
    max_concurrent_requests: int = 100
    request_timeout_seconds: int = 30
    websocket_heartbeat_interval: int = 30

    # Security Settings
    jwt_secret_key: Optional[str] = None
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        """Parse CORS origins from environment variable"""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("detection_confidence_threshold")
    @classmethod
    def validate_confidence_threshold(cls, value: float) -> float:
        """Validate confidence threshold is between 0 and 1 inclusive"""
        if not 0.0 <= value <= 1.0:
            raise ValueError("Detection confidence threshold must be between 0.0 and 1.0 inclusive")
        return value

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "env_prefix": "TRAFFIC_",
    }


class DevelopmentSettings(ApplicationSettings):
    """Development environment configuration"""
    debug_mode: bool = True
    log_level: str = "DEBUG"
    api_host: str = "127.0.0.1"


class ProductionSettings(ApplicationSettings):
    """Production environment configuration"""
    debug_mode: bool = False
    log_level: str = "WARNING"
    enable_file_logging: bool = True
    allowed_origins: List[str] = [
        "https://your-frontend-domain.com",
        "https://*.vercel.app",
        "https://*.railway.app",
        "https://*.render.com",
    ]


class TestingSettings(ApplicationSettings):
    """Testing environment configuration"""
    debug_mode: bool = True
    database_name: str = "traffic_management_test"
    redis_connection_string: str = "redis://localhost:6379/1"
    log_level: str = "DEBUG"


@lru_cache()
def get_application_settings() -> ApplicationSettings:
    """Get application settings based on environment"""
    environment = os.getenv("ENVIRONMENT", "development").lower()

    if environment == "production":
        return ProductionSettings()
    elif environment == "testing":
        return TestingSettings()
    else:
        return DevelopmentSettings()


# Global settings instance
settings = get_application_settings()
