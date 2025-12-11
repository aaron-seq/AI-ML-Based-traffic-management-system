"""
Configuration management for AI Traffic Management System
Handles environment variables and application settings with enhanced security
"""

import os
import secrets
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings
from pydantic import field_validator, ValidationError


class ApplicationSettings(BaseSettings):
    """Application configuration with environment variable support and security hardening"""

    # Application Info
    application_name: str = "AI Traffic Management System"
    application_version: str = "2.0.0"
    debug_mode: bool = False
    environment: str = "development"

    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api"

    # CORS Settings - SECURITY HARDENED
    allowed_origins: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    allowed_methods: List[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allowed_headers: List[str] = ["*"]

    # Database Configuration with validation
    mongodb_connection_string: str = "mongodb://localhost:27017"
    database_name: str = "traffic_management"

    # Redis Configuration with validation
    redis_connection_string: str = "redis://localhost:6379"
    redis_cache_ttl: int = 3600  # 1 hour

    # AI Model Configuration
    model_name: str = "yolov8n.pt"
    detection_confidence_threshold: float = 0.25
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

    # Security Settings - SECURITY HARDENED
    jwt_secret_key: Optional[str] = None
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24

    # Rate limiting settings
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst_requests: int = 10

    # File upload security
    max_upload_size_mb: int = 10
    allowed_image_types: List[str] = [".jpg", ".jpeg", ".png", ".bmp"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        """Parse CORS origins from environment variable with security validation"""
        if isinstance(value, str):
            origins = [origin.strip() for origin in value.split(",") if origin.strip()]
            # Security: Reject wildcard in production
            if (
                "*" in origins
                and os.getenv("ENVIRONMENT", "development").lower() == "production"
            ):
                raise ValueError("Wildcard CORS origins not allowed in production")
            return origins
        return value

    @field_validator("detection_confidence_threshold")
    @classmethod
    def validate_confidence_threshold(cls, value: float) -> float:
        """Validate confidence threshold is between 0 and 1 inclusive"""
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                "Detection confidence threshold must be between 0.0 and 1.0 inclusive"
            )
        return value

    @field_validator("mongodb_connection_string")
    @classmethod
    def validate_mongodb_connection(cls, value: str) -> str:
        """Validate MongoDB connection string format"""
        if not value.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError(
                "MongoDB connection string must start with mongodb:// or mongodb+srv://"
            )
        return value

    @field_validator("redis_connection_string")
    @classmethod
    def validate_redis_connection(cls, value: str) -> str:
        """Validate Redis connection string format"""
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError(
                "Redis connection string must start with redis:// or rediss://"
            )
        return value

    @field_validator("jwt_secret_key", mode="before")
    @classmethod
    def validate_jwt_secret(cls, value: Optional[str]) -> str:
        """Ensure JWT secret key is present and secure"""
        if not value:
            # Generate a secure random key if not provided
            generated_key = secrets.token_urlsafe(64)
            print(
                f"WARNING: JWT secret key not set. Generated temporary key: {generated_key[:16]}..."
            )
            print("Set TRAFFIC_JWT_SECRET_KEY environment variable for production")
            return generated_key

        # Validate key strength
        if len(value) < 32:
            raise ValueError("JWT secret key must be at least 32 characters long")

        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Validate log level"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if value.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return value.upper()

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "env_prefix": "TRAFFIC_",
        "validate_assignment": True,
    }


class DevelopmentSettings(ApplicationSettings):
    """Development environment configuration"""

    debug_mode: bool = True
    log_level: str = "DEBUG"
    api_host: str = "127.0.0.1"
    environment: str = "development"


class ProductionSettings(ApplicationSettings):
    """Production environment configuration with enhanced security"""

    debug_mode: bool = False
    log_level: str = "INFO"
    enable_file_logging: bool = True
    environment: str = "production"

    # Production-specific CORS origins - NO WILDCARDS
    allowed_origins: List[str] = [
        "https://your-frontend-domain.com",
        "https://*.vercel.app",
        "https://*.railway.app",
        "https://*.render.com",
    ]

    # Tighter rate limits for production
    rate_limit_requests_per_minute: int = 30
    rate_limit_burst_requests: int = 5


class TestingSettings(ApplicationSettings):
    """Testing environment configuration"""

    debug_mode: bool = True
    database_name: str = "traffic_management_test"
    redis_connection_string: str = "redis://localhost:6379/1"
    log_level: str = "DEBUG"
    environment: str = "testing"

    # Faster settings for testing
    jwt_expiration_hours: int = 1
    redis_cache_ttl: int = 60


@lru_cache()
def get_application_settings() -> ApplicationSettings:
    """Get application settings based on environment with error handling"""
    environment = os.getenv("ENVIRONMENT", "development").lower()

    try:
        if environment == "production":
            return ProductionSettings()
        elif environment == "testing":
            return TestingSettings()
        else:
            return DevelopmentSettings()
    except ValidationError as e:
        print(f"Configuration validation error: {e}")
        print("Using development settings with default values")
        return DevelopmentSettings()
    except Exception as e:
        print(f"Unexpected configuration error: {e}")
        print("Using development settings with default values")
        return DevelopmentSettings()


def validate_configuration() -> bool:
    """Validate current configuration and return True if valid"""
    try:
        # Test configuration by accessing key properties
        _ = settings.jwt_secret_key
        _ = settings.mongodb_connection_string
        _ = settings.redis_connection_string

        # Validate critical security settings
        if settings.environment == "production":
            if "*" in settings.allowed_origins:
                print("ERROR: Wildcard CORS origins not allowed in production")
                return False

            if not settings.jwt_secret_key or len(settings.jwt_secret_key) < 32:
                print(
                    "ERROR: JWT secret key must be at least 32 characters in production"
                )
                return False

        return True

    except Exception as e:
        print(f"Configuration validation failed: {e}")
        return False


# Global settings instance
settings = get_application_settings()

# Validate configuration on import
if not validate_configuration():
    print("WARNING: Configuration validation failed. Check environment variables.")
