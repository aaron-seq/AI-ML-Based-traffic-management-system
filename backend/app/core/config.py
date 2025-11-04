"""
FastAPI application settings and configuration management
"""

import os
import secrets
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationSettings(BaseSettings):
    """Core application settings"""

    # Application Info
    application_name: str = "AI Traffic Management System"
    application_version: str = "2.0.0"

    # Environment
    environment: str = Field("development", env="ENVIRONMENT")
    debug_mode: bool = False

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api"

    # Logging
    log_level: str = "INFO"
    log_file_path: str = "traffic_management.log"
    enable_file_logging: bool = True

    # AI Model Settings
    model_name: str = "yolov8n.pt"
    detection_confidence_threshold: float = Field(0.4, ge=0.0, le=1.0)
    non_max_suppression_threshold: float = Field(0.5, ge=0.0, le=1.0)
    enable_gpu_acceleration: bool = False
    model_cache_directory: str = "./models"

    # Security
    jwt_secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    jwt_algorithm: str = "HS256"
    jwt_token_expire_minutes: int = 30
    
    # CORS
    allowed_origins: List[str] = ["*"]
    allowed_methods: List[str] = ["*"]
    allowed_headers: List[str] = ["*"]
    
    # Rate Limiting
    rate_limit_requests_per_minute: int = 100
    
    # Database and Cache
    mongodb_connection_string: Optional[str] = None
    redis_connection_string: str = "redis://localhost:6379/0"
    database_name: str = "traffic_management"
    
    # Traffic Management
    default_green_signal_duration: int = 30
    emergency_override_duration: int = 60
    websocket_update_interval: int = 2
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TRAFFIC_",
        case_sensitive=False,
        extra="ignore"
    )

    @validator("jwt_secret_key")
    def validate_jwt_secret_key(cls, value):
        if len(value) < 32:
            raise ValueError("JWT secret key must be at least 32 characters long")
        return value

    @validator("environment")
    def validate_environment(cls, value):
        if value not in ["development", "production"]:
            raise ValueError("ENVIRONMENT must be 'development' or 'production'")
        return value


class DevelopmentSettings(ApplicationSettings):
    """Development environment specific settings"""

    debug_mode: bool = True
    log_level: str = "DEBUG"
    api_host: str = "0.0.0.0"
    environment: str = "development"

    model_config = SettingsConfigDict(env_prefix="DEV_TRAFFIC_")


class ProductionSettings(ApplicationSettings):
    """Production environment specific settings"""

    debug_mode: bool = False
    log_level: str = "INFO"
    environment: str = "production"
    
    # Stricter production settings
    allowed_origins: List[str] = []  # Should be explicitly set
    rate_limit_requests_per_minute: int = 30
    
    model_config = SettingsConfigDict(env_prefix="PROD_TRAFFIC_")


@lru_cache()
def get_application_settings() -> ApplicationSettings:
    """Factory to get application settings based on environment"""

    environment = os.getenv("ENVIRONMENT", "development").lower()
    
    if environment == "production":
        return ProductionSettings()

    return DevelopmentSettings()

settings = get_application_settings()
