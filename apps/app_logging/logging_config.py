from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from apps.settings.config import get_settings


VALID_LOG_LEVELS = {
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
}

VALID_LOG_FORMATS = {
    "console",
    "json",
}


@dataclass(frozen=True)
class LoggingSettings:
    """Logging-specific application configuration."""

    app_name: str
    environment: str

    log_level: str
    log_format: str

    queue_size: int

    slow_request_threshold_ms: int

    shutdown_flush_timeout_seconds: float

    log_request_body: bool
    log_response_body: bool

    @property
    def is_production(self) -> bool:
        return (
            self.environment.strip().lower()
            == "production"
        )


@lru_cache
def get_logging_settings() -> LoggingSettings:
    """
    Build logging configuration from the application's
    central Settings object.

    This ensures logging uses the same .env_dev /
    .env_prod configuration as the rest of the project.
    """

    settings = get_settings()

    log_level = (
        settings.log_level
        .strip()
        .upper()
    )

    if log_level not in VALID_LOG_LEVELS:
        raise ValueError(
            "LOG_LEVEL must be one of: "
            f"{', '.join(sorted(VALID_LOG_LEVELS))}"
        )

    log_format = (
        settings.log_format
        .strip()
        .lower()
    )

    if log_format not in VALID_LOG_FORMATS:
        raise ValueError(
            "LOG_FORMAT must be either "
            "'console' or 'json'"
        )

    if settings.log_queue_size < 100:
        raise ValueError(
            "LOG_QUEUE_SIZE must be >= 100"
        )

    if (
        settings.log_slow_request_threshold_ms
        < 100
    ):
        raise ValueError(
            "LOG_SLOW_REQUEST_THRESHOLD_MS "
            "must be >= 100"
        )

    if (
        settings.log_shutdown_flush_timeout_seconds
        < 0.1
    ):
        raise ValueError(
            "LOG_SHUTDOWN_FLUSH_TIMEOUT_SECONDS "
            "must be >= 0.1"
        )

    return LoggingSettings(
        app_name=settings.app_name,

        environment=(
            settings.environment
        ),

        log_level=log_level,

        log_format=log_format,

        queue_size=(
            settings.log_queue_size
        ),

        slow_request_threshold_ms=(
            settings
            .log_slow_request_threshold_ms
        ),

        shutdown_flush_timeout_seconds=(
            settings
            .log_shutdown_flush_timeout_seconds
        ),

        log_request_body=(
            settings.log_request_body
        ),

        log_response_body=(
            settings.log_response_body
        ),
    )
