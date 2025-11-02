"""
Test suite for configuration management system
Tests security validations and environment-specific settings
"""

import os
import pytest
from unittest.mock import patch

from pydantic import ValidationError

from app.core.config import (
    ApplicationSettings,
    DevelopmentSettings,
    ProductionSettings,
    TestingSettings,
    get_application_settings,
    validate_configuration
)


class TestApplicationSettings:
    """Test core application settings validation"""
    
    def test_default_settings_valid(self):
        """Test that default settings are valid"""
        settings = ApplicationSettings()
        assert settings.application_name == "AI Traffic Management System"
        assert settings.api_port == 8000
        assert 0.0 <= settings.detection_confidence_threshold <= 1.0
    
    def test_confidence_threshold_validation(self):
        """Test confidence threshold validation bounds"""
        # Valid thresholds
        ApplicationSettings(detection_confidence_threshold=0.0)
        ApplicationSettings(detection_confidence_threshold=0.5)
        ApplicationSettings(detection_confidence_threshold=1.0)
        
        # Invalid thresholds
        with pytest.raises(ValidationError):
            ApplicationSettings(detection_confidence_threshold=-0.1)
        
        with pytest.raises(ValidationError):
            ApplicationSettings(detection_confidence_threshold=1.1)
    
    def test_mongodb_connection_validation(self):
        """Test MongoDB connection string validation"""
        # Valid connections
        ApplicationSettings(mongodb_connection_string="mongodb://localhost:27017")
        ApplicationSettings(mongodb_connection_string="mongodb+srv://cluster.mongodb.net")
        
        # Invalid connections
        with pytest.raises(ValidationError):
            ApplicationSettings(mongodb_connection_string="invalid://localhost")
        
        with pytest.raises(ValidationError):
            ApplicationSettings(mongodb_connection_string="http://localhost")
    
    def test_redis_connection_validation(self):
        """Test Redis connection string validation"""
        # Valid connections
        ApplicationSettings(redis_connection_string="redis://localhost:6379")
        ApplicationSettings(redis_connection_string="rediss://secure.redis.com:6380")
        
        # Invalid connections
        with pytest.raises(ValidationError):
            ApplicationSettings(redis_connection_string="invalid://localhost")
        
        with pytest.raises(ValidationError):
            ApplicationSettings(redis_connection_string="http://localhost")
    
    def test_jwt_secret_key_generation(self):
        """Test JWT secret key generation when not provided"""
        settings = ApplicationSettings(jwt_secret_key=None)
        assert settings.jwt_secret_key is not None
        assert len(settings.jwt_secret_key) >= 32
    
    def test_jwt_secret_key_validation(self):
        """Test JWT secret key strength validation"""
        # Valid key
        long_key = "a" * 32
        settings = ApplicationSettings(jwt_secret_key=long_key)
        assert settings.jwt_secret_key == long_key
        
        # Invalid short key
        with pytest.raises(ValidationError):
            ApplicationSettings(jwt_secret_key="short")
    
    def test_cors_origins_parsing(self):
        """Test CORS origins string parsing"""
        # String input
        settings = ApplicationSettings(allowed_origins="http://localhost:3000,https://example.com")
        assert "http://localhost:3000" in settings.allowed_origins
        assert "https://example.com" in settings.allowed_origins
        
        # List input
        origins = ["http://localhost:3000", "https://example.com"]
        settings = ApplicationSettings(allowed_origins=origins)
        assert settings.allowed_origins == origins
    
    @patch.dict(os.environ, {"ENVIRONMENT": "production"})
    def test_cors_wildcard_rejected_in_production(self):
        """Test that wildcard CORS origins are rejected in production"""
        with pytest.raises(ValidationError, match="Wildcard CORS origins not allowed"):
            ApplicationSettings(allowed_origins="*,https://example.com")
    
    def test_log_level_validation(self):
        """Test log level validation"""
        # Valid levels
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            settings = ApplicationSettings(log_level=level)
            assert settings.log_level == level
            
            # Test case insensitive
            settings = ApplicationSettings(log_level=level.lower())
            assert settings.log_level == level
        
        # Invalid level
        with pytest.raises(ValidationError):
            ApplicationSettings(log_level="INVALID")


class TestEnvironmentSettings:
    """Test environment-specific settings"""
    
    def test_development_settings(self):
        """Test development environment settings"""
        settings = DevelopmentSettings()
        assert settings.debug_mode is True
        assert settings.log_level == "DEBUG"
        assert settings.api_host == "127.0.0.1"
        assert settings.environment == "development"
    
    def test_production_settings(self):
        """Test production environment settings"""
        settings = ProductionSettings()
        assert settings.debug_mode is False
        assert settings.log_level == "INFO"
        assert settings.environment == "production"
        
        # Production should not have wildcards in CORS
        assert "*" not in settings.allowed_origins
        
        # Should have tighter rate limits
        assert settings.rate_limit_requests_per_minute <= 30
    
    def test_testing_settings(self):
        """Test testing environment settings"""
        settings = TestingSettings()
        assert settings.debug_mode is True
        assert settings.database_name == "traffic_management_test"
        assert settings.environment == "testing"
        assert "6379/1" in settings.redis_connection_string  # Test database


class TestConfigurationFactory:
    """Test configuration factory functions"""
    
    @patch.dict(os.environ, {"ENVIRONMENT": "development"})
    def test_get_development_settings(self):
        """Test getting development settings"""
        # Clear cache
        get_application_settings.cache_clear()
        settings = get_application_settings()
        assert isinstance(settings, DevelopmentSettings)
        assert settings.debug_mode is True
    
    @patch.dict(os.environ, {"ENVIRONMENT": "production"})
    def test_get_production_settings(self):
        """Test getting production settings"""
        get_application_settings.cache_clear()
        settings = get_application_settings()
        assert isinstance(settings, ProductionSettings)
        assert settings.debug_mode is False
    
    @patch.dict(os.environ, {"ENVIRONMENT": "testing"})
    def test_get_testing_settings(self):
        """Test getting testing settings"""
        get_application_settings.cache_clear()
        settings = get_application_settings()
        assert isinstance(settings, TestingSettings)
        assert settings.database_name == "traffic_management_test"
    
    @patch.dict(os.environ, {}, clear=True)
    def test_default_to_development(self):
        """Test defaulting to development when ENVIRONMENT not set"""
        get_application_settings.cache_clear()
        settings = get_application_settings()
        assert isinstance(settings, DevelopmentSettings)


if __name__ == "__main__":
    pytest.main([__file__])
