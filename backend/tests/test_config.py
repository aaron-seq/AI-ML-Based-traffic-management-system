"""Unit tests for configuration"""

import pytest
from app.core.config import ApplicationSettings

class TestApplicationSettings:
    """Test application settings"""
    
    def test_jwt_secret_key_generation(self):
        """Test that a JWT secret key is generated if not provided"""
        settings = ApplicationSettings()
        assert settings.jwt_secret_key is not None
        assert len(settings.jwt_secret_key) >= 32
