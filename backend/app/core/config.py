"""Application configuration.

Every setting can be overridden with a ``TRAFFIC_``-prefixed environment
variable (for example ``TRAFFIC_DETECTION_CONFIDENCE_THRESHOLD=0.35``) or via a
``.env`` file. ``ENVIRONMENT`` selects the profile: ``development`` (default),
``testing`` or ``production``.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "testing", "production"]

#: Environment variable that selects which settings profile to load.
ENVIRONMENT_VARIABLE = "ENVIRONMENT"


def _split_csv(value: Any) -> Any:
    """Allow list-valued settings to be given as comma-separated strings."""
    if isinstance(value, str):
        stripped = value.strip()
        # A JSON array is handled natively by pydantic-settings.
        if stripped.startswith("["):
            return value
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return value


class ApplicationSettings(BaseSettings):
    """Base configuration shared by every environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TRAFFIC_",
        case_sensitive=False,
        validate_assignment=True,
        extra="ignore",
        # ``model_name`` etc. would otherwise collide with pydantic's reserved
        # ``model_`` namespace and emit warnings on every import.
        protected_namespaces=(),
    )

    # --- Application identity ------------------------------------------------
    application_name: str = "AI Traffic Management System"
    application_version: str = "3.0.0"
    environment: Environment = "development"
    debug_mode: bool = False

    # --- HTTP server ---------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api"
    docs_enabled: bool = True

    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    allowed_methods: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allowed_headers: list[str] = ["*"]
    trusted_hosts: list[str] = ["*"]

    # --- Detection model -----------------------------------------------------
    model_name: str = "yolov8n.pt"
    model_cache_directory: str = "./models"
    detection_confidence_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.35
    non_max_suppression_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.45
    detection_image_size: Annotated[int, Field(ge=64, le=2048)] = 640
    enable_gpu_acceleration: bool = False
    tracker_config: str = "bytetrack.yaml"
    #: Frames to skip between inferences when analysing video (1 = every frame).
    video_frame_stride: Annotated[int, Field(ge=1, le=30)] = 3
    #: Hard cap on frames analysed per video upload, to bound request time.
    video_max_frames: Annotated[int, Field(ge=1, le=10_000)] = 300

    # --- Signal timing -------------------------------------------------------
    default_green_signal_duration: Annotated[int, Field(ge=1)] = 30
    yellow_signal_duration: Annotated[int, Field(ge=1)] = 3
    all_red_clearance_duration: Annotated[int, Field(ge=0)] = 2
    minimum_green_duration: Annotated[int, Field(ge=1)] = 10
    maximum_green_duration: Annotated[int, Field(ge=1)] = 120
    #: Extra green seconds granted per queued vehicle by the adaptive controller.
    seconds_per_queued_vehicle: Annotated[float, Field(ge=0.0, le=10.0)] = 2.0
    #: Controller tick interval in seconds.
    control_loop_interval_seconds: Annotated[float, Field(gt=0.0, le=10.0)] = 1.0

    # --- Pedestrians ---------------------------------------------------------
    pedestrian_crossing_duration: Annotated[int, Field(ge=1)] = 12
    #: Longest a pedestrian request may wait before it pre-empts vehicle phases.
    pedestrian_max_wait_seconds: Annotated[int, Field(ge=1)] = 90

    # --- Emergency pre-emption ----------------------------------------------
    emergency_detection_enabled: bool = True
    emergency_override_duration: Annotated[int, Field(ge=1)] = 45

    # --- Corridor coordination ----------------------------------------------
    green_wave_enabled: bool = True
    #: Design speed for green-wave offsets, in km/h.
    green_wave_design_speed_kph: Annotated[float, Field(gt=0)] = 50.0

    # --- Impact model --------------------------------------------------------
    # Defaults are conservative mid-range figures drawn from published urban
    # traffic studies; override them with locally measured values.
    idle_fuel_litres_per_hour: Annotated[float, Field(ge=0)] = 0.9
    co2_kg_per_litre_petrol: Annotated[float, Field(ge=0)] = 2.31
    average_vehicle_occupancy: Annotated[float, Field(gt=0)] = 1.4
    value_of_time_per_hour: Annotated[float, Field(ge=0)] = 8.0
    impact_currency: str = "USD"
    #: Fixed-time baseline cycle the adaptive controller is compared against.
    baseline_fixed_cycle_seconds: Annotated[int, Field(ge=1)] = 120

    # --- Forecasting ---------------------------------------------------------
    forecast_smoothing_alpha: Annotated[float, Field(gt=0.0, le=1.0)] = 0.35
    forecast_min_observations: Annotated[int, Field(ge=2)] = 5

    # --- Persistence ---------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/traffic.db"
    database_echo: bool = False
    persistence_enabled: bool = True
    #: Detection/among-cycle records older than this are pruned on startup.
    retention_days: Annotated[int, Field(ge=1)] = 30

    redis_connection_string: str = "redis://localhost:6379/0"
    redis_cache_ttl: Annotated[int, Field(ge=1)] = 3600
    redis_enabled: bool = False

    # --- Hardware bridge -----------------------------------------------------
    #: HTTP endpoint that receives signal-state changes (controller, PLC, relay
    #: board, Arduino gateway...). Empty disables the bridge.
    hardware_webhook_url: str = ""
    hardware_webhook_timeout_seconds: Annotated[float, Field(gt=0)] = 3.0
    hardware_webhook_token: str = ""

    # --- Logging -------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False
    enable_file_logging: bool = True
    log_file_path: str = "./logs/traffic_system.log"

    # --- Security ------------------------------------------------------------
    #: When set, write endpoints require ``X-API-Key``. Empty leaves the API open
    #: (fine for local demos, rejected by ``validate_configuration`` in prod).
    api_key: str = ""
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: Annotated[int, Field(ge=1)] = 24

    rate_limit_requests_per_minute: Annotated[int, Field(ge=1)] = 120
    rate_limit_upload_requests_per_minute: Annotated[int, Field(ge=1)] = 20

    max_upload_size_mb: Annotated[int, Field(ge=1, le=512)] = 25
    allowed_image_types: list[str] = [".jpg", ".jpeg", ".png", ".bmp", ".webp"]
    allowed_video_types: list[str] = [".mp4", ".avi", ".mov", ".mkv", ".webm"]

    # --- Performance ---------------------------------------------------------
    max_concurrent_inferences: Annotated[int, Field(ge=1, le=64)] = 2
    request_timeout_seconds: Annotated[int, Field(ge=1)] = 60
    websocket_broadcast_interval_seconds: Annotated[float, Field(gt=0)] = 1.0

    # --- Validators ----------------------------------------------------------
    _split_lists = field_validator(
        "allowed_origins",
        "allowed_methods",
        "allowed_headers",
        "trusted_hosts",
        "allowed_image_types",
        "allowed_video_types",
        mode="before",
    )(_split_csv)

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if "://" not in value:
            raise ValueError(
                "database_url must be a SQLAlchemy URL, e.g. sqlite+aiosqlite:///./data/traffic.db"
            )
        return value

    @field_validator("redis_connection_string")
    @classmethod
    def _validate_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://", "unix://")):
            raise ValueError("redis_connection_string must start with redis://, rediss:// or unix://")
        return value

    @field_validator("jwt_secret_key", mode="after")
    @classmethod
    def _validate_jwt_secret(cls, value: str) -> str:
        if value and len(value) < 32:
            raise ValueError("jwt_secret_key must be at least 32 characters when set")
        return value

    # --- Derived helpers -----------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def inference_device(self) -> str:
        return "cuda" if self.enable_gpu_acceleration else "cpu"

    def resolved_jwt_secret(self) -> str:
        """Return the JWT secret, generating an ephemeral one if unset.

        An ephemeral secret invalidates every token on restart, which is
        acceptable for development but never for production -- see
        :func:`validate_configuration`.
        """
        if not self.jwt_secret_key:
            object.__setattr__(self, "jwt_secret_key", secrets.token_urlsafe(48))
        return self.jwt_secret_key


class DevelopmentSettings(ApplicationSettings):
    environment: Environment = "development"
    debug_mode: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG"
    docs_enabled: bool = True


class TestingSettings(ApplicationSettings):
    environment: Environment = "testing"
    debug_mode: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING"
    enable_file_logging: bool = False
    persistence_enabled: bool = False
    database_url: str = "sqlite+aiosqlite:///:memory:"
    redis_connection_string: str = "redis://localhost:6379/1"
    jwt_expiration_hours: int = 1
    redis_cache_ttl: int = 60


class ProductionSettings(ApplicationSettings):
    environment: Environment = "production"
    debug_mode: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True
    docs_enabled: bool = False
    enable_file_logging: bool = True
    rate_limit_requests_per_minute: int = 60
    rate_limit_upload_requests_per_minute: int = 10


_PROFILES: dict[str, type[ApplicationSettings]] = {
    "development": DevelopmentSettings,
    "testing": TestingSettings,
    "production": ProductionSettings,
}


@lru_cache
def get_application_settings() -> ApplicationSettings:
    """Load the settings profile named by ``ENVIRONMENT`` (cached)."""
    name = os.getenv(ENVIRONMENT_VARIABLE, "development").strip().lower()
    profile = _PROFILES.get(name, DevelopmentSettings)
    try:
        return profile()
    except ValidationError as error:  # pragma: no cover - depends on bad env
        raise RuntimeError(
            f"Invalid configuration for ENVIRONMENT={name!r}:\n{error}\n"
            "Fix the offending TRAFFIC_* environment variables and restart."
        ) from error


def validate_configuration(config: ApplicationSettings | None = None) -> list[str]:
    """Return a list of configuration problems; empty means the config is sound.

    Unlike the previous boolean version this reports *what* is wrong, and it
    treats the production-only requirements as errors rather than warnings.
    """
    config = config or settings
    problems: list[str] = []

    if config.minimum_green_duration > config.maximum_green_duration:
        problems.append("minimum_green_duration must not exceed maximum_green_duration")

    if config.is_production:
        if "*" in config.allowed_origins:
            problems.append("wildcard CORS origin '*' is not allowed in production")
        if "*" in config.trusted_hosts:
            problems.append(
                "wildcard trusted host '*' is not allowed in production; set TRAFFIC_TRUSTED_HOSTS"
            )
        if not config.api_key:
            problems.append("TRAFFIC_API_KEY must be set in production to protect write endpoints")
        if not config.jwt_secret_key:
            problems.append("TRAFFIC_JWT_SECRET_KEY must be set in production")
        if config.debug_mode:
            problems.append("debug_mode must be disabled in production")

    return problems


#: Module-level singleton used throughout the application.
settings: ApplicationSettings = get_application_settings()
