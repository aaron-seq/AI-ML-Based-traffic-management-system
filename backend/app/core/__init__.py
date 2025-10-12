"""
Core module for AI Traffic Management System
Contains configuration, logging, and shared utilities
"""

from .config import get_application_settings, settings
from .logger import get_application_logger, setup_logging

__all__ = [
    "get_application_settings",
    "settings", 
    "get_application_logger",
    "setup_logging"
]
