"""Logging setup: coloured console output for humans, JSON for log shippers."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

from .config import settings

#: Attributes present on every LogRecord; anything else came from ``extra=``.
_RESERVED_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {
    "message",
    "asctime",
    "taskName",
}

_LEVEL_COLOURS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;35m",
}
_RESET = "\033[0m"


class ColourFormatter(logging.Formatter):
    """Console formatter that colours the level name when attached to a TTY.

    The colour is applied to a copy of the level name rather than mutated onto
    the record, so a second handler (the file handler) still sees clean text.
    """

    def __init__(self, *args: Any, use_colour: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.use_colour = use_colour

    def format(self, record: logging.LogRecord) -> str:
        if not self.use_colour:
            return super().format(record)

        original = record.levelname
        colour = _LEVEL_COLOURS.get(original, "")
        record.levelname = f"{colour}{original:<8}{_RESET}" if colour else original
        try:
            return super().format(record)
        finally:
            record.levelname = original


class JsonFormatter(logging.Formatter):
    """One JSON object per line, including any ``extra=`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def setup_logging() -> None:
    """Configure root logging. Safe to call more than once."""
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(settings.log_level)
    if settings.log_json:
        console.setFormatter(JsonFormatter())
    else:
        console.setFormatter(
            ColourFormatter(
                fmt="%(asctime)s | %(name)-32s | %(levelname)-8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
                use_colour=sys.stdout.isatty(),
            )
        )
    root.addHandler(console)

    if settings.enable_file_logging:
        try:
            log_path = Path(settings.log_file_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                filename=log_path,
                maxBytes=10_000_000,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(settings.log_level)
            file_handler.setFormatter(JsonFormatter())
            root.addHandler(file_handler)
        except OSError as error:
            # A read-only filesystem must not stop the service from booting.
            root.warning("File logging disabled: %s", error)

    # These are chatty at INFO/DEBUG and add nothing over our own logging.
    # aiosqlite in particular logs every cursor operation at DEBUG.
    for noisy in (
        "uvicorn.access",
        "httpx",
        "httpcore",
        "asyncio",
        "multipart",
        "python_multipart",
        "aiosqlite",
        "sqlalchemy.engine",
        "matplotlib",
        "PIL",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    get_application_logger("startup").info(
        "Logging initialised (level=%s, json=%s)", settings.log_level, settings.log_json
    )


def get_application_logger(name: str) -> logging.Logger:
    """Return a namespaced application logger."""
    return logging.getLogger(f"traffic.{name}")


class LoggerMixin:
    """Gives a class a lazily-created logger plus two convenience helpers."""

    @property
    def logger(self) -> logging.Logger:
        cached = getattr(self, "_logger", None)
        if cached is None:
            cached = get_application_logger(type(self).__name__)
            self._logger = cached
        return cached

    def log_performance(self, operation: str, duration_seconds: float, **fields: Any) -> None:
        """Record how long an operation took, at DEBUG level."""
        self.logger.debug(
            "%s finished in %.3fs",
            operation,
            duration_seconds,
            extra={"operation": operation, "duration_seconds": round(duration_seconds, 4), **fields},
        )

    def log_error_with_context(self, error: Exception, context: str, **fields: Any) -> None:
        """Record an exception together with the operation that raised it."""
        self.logger.error(
            "%s failed: %s",
            context,
            error,
            exc_info=True,
            extra={"operation": context, "error_type": type(error).__name__, **fields},
        )
