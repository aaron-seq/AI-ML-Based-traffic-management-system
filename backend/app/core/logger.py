"""
Logging configuration for AI Traffic Management System
Provides structured logging with rotation and performance monitoring
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

from .config import settings


class CustomFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""
    
    COLORS = {
        "DEBUG": "\033[36m",    # Cyan
        "INFO": "\033[32m",     # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[35m", # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


class PerformanceFilter(logging.Filter):
    """Filter to add performance metrics to log records"""
    
    def filter(self, record):
        # Add custom attributes for performance monitoring
        if not hasattr(record, 'request_id'):
            record.request_id = 'N/A'
        if not hasattr(record, 'execution_time'):
            record.execution_time = 'N/A'
        return True


def setup_logging() -> None:
    """Configure application logging with file rotation and console output"""
    
    # Create logs directory if it doesn't exist
    log_file_path = Path(settings.log_file_path)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = CustomFormatter(
        fmt="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(PerformanceFilter())
    
    # File handler with rotation
    if settings.enable_file_logging:
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file_path,
            maxBytes=10_000_000,  # 10MB
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(getattr(logging, settings.log_level.upper()))
        file_formatter = logging.Formatter(
            fmt="%(asctime)s | %(name)-20s | %(levelname)-8s | "
                "%(request_id)s | %(execution_time)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(PerformanceFilter())
        root_logger.addHandler(file_handler)
    
    root_logger.addHandler(console_handler)
    
    # Set specific logger levels
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    # Application logger
    app_logger = logging.getLogger("traffic_management")
    app_logger.info("Logging system initialized successfully")


def get_application_logger(name: str) -> logging.Logger:
    """Get a logger instance for the application"""
    return logging.getLogger(f"traffic_management.{name}")


class LoggerMixin:
    """Mixin to add logging capabilities to any class"""
    
    @property
    def logger(self) -> logging.Logger:
        """Get logger instance for this class"""
        if not hasattr(self, '_logger'):
            class_name = self.__class__.__name__
            self._logger = get_application_logger(class_name.lower())
        return self._logger
    
    def log_performance(self, operation: str, execution_time: float, **kwargs):
        """Log performance metrics for an operation"""
        extra = {
            'request_id': kwargs.get('request_id', 'N/A'),
            'execution_time': f'{execution_time:.3f}s'
        }
        self.logger.info(
            f"Performance: {operation} completed", 
            extra=extra
        )
    
    def log_error_with_context(self, error: Exception, context: str, **kwargs):
        """Log error with additional context information"""
        extra = {
            'request_id': kwargs.get('request_id', 'N/A'),
            'execution_time': 'N/A'
        }
        self.logger.error(
            f"Error in {context}: {str(error)}", 
            exc_info=True,
            extra=extra
        )
