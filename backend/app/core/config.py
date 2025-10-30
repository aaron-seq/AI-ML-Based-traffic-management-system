"""
Configuration management for AI Traffic Management System
Handles environment variables and application settings
"""

import os
from functools import lru_cache
from typing import List, Optional

try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings

from pydantic import validator


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
    jwt_secret_key: Optional[str] = "your-secret-key-change-in-production"  # Fixed default security issue
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    
    @validator("allowed_origins", pre=True)
    def parse_cors_origins(cls, value):
        """Parse CORS origins from environment variable"""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",")]
        return value
    
    @validator("detection_confidence_threshold")
    def validate_confidence_threshold(cls, value):
        """Validate confidence threshold is between 0 and 1"""
        if not 0.0 < value < 1.0:
            raise ValueError("Detection confidence threshold must be between 0 and 1")
        return value
    
    @validator("jwt_secret_key")
    def validate_jwt_secret(cls, value):
        """Validate JWT secret key is provided"""
        if not value or value == "None":
            raise ValueError("JWT secret key must be provided for security")
        if len(value) < 32:
            raise ValueError("JWT secret key must be at least 32 characters long")
        return value
    
    @validator("mongodb_connection_string")
    def validate_mongodb_connection(cls, value):
        """Validate MongoDB connection string format"""
        if not value.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("Invalid MongoDB connection string format")
        return value
    
    @validator("redis_connection_string")
    def validate_redis_connection(cls, value):
        """Validate Redis connection string format"""
        if not value.startswith("redis://"):
            raise ValueError("Invalid Redis connection string format")
        return value
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        env_prefix = "TRAFFIC_"


class DevelopmentSettings(ApplicationSettings):
    """Development environment configuration"""
    debug_mode: bool = True
    log_level: str = "DEBUG"
    api_host: str = "127.0.0.1"
    allowed_origins: List[str] = [
        "http://localhost:3000", 
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ]


class ProductionSettings(ApplicationSettings):
    """Production environment configuration"""
    debug_mode: bool = False
    log_level: str = "WARNING"
    enable_file_logging: bool = True
    allowed_origins: List[str] = [
        "https://your-frontend-domain.com",
        "https://*.vercel.app",
        "https://*.railway.app",
        "https://*.render.com"
    ]


class TestingSettings(ApplicationSettings):
    """Testing environment configuration"""
    debug_mode: bool = True
    database_name: str = "traffic_management_test"
    redis_connection_string: str = "redis://localhost:6379/1"
    log_level: str = "DEBUG"
    jwt_secret_key: str = "test-secret-key-minimum-32-characters-long"


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
