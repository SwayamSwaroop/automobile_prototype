from __future__ import annotations

import logging
import queue
import sys
from dataclasses import dataclass

from apps.app_logging.logging_config import (
    get_logging_settings,
)
from apps.app_logging.logging_filter import (
    LoggingContextFilter,
)
from apps.app_logging.logging_formatter import (
    LocalConsoleFormatter,
    ProductionJsonFormatter,
)
from apps.app_logging.logging_queue import (
    LoggingQueueSnapshot,
    LoggingQueueStats,
    NonBlockingQueueHandler,
    SafeQueueListener,
)


@dataclass
class LoggingRuntime:
    """
    Runtime objects used by the centralized
    application logging infrastructure.
    """

    log_queue: queue.Queue[logging.LogRecord]

    listener: SafeQueueListener

    stats: LoggingQueueStats

    queue_capacity: int

    shutdown_timeout_seconds: float

    started: bool = False

    def start(self) -> None:
        """
        Start the background logging listener.

        Safe to call more than once.
        """

        if self.started:
            return

        self.listener.start()

        self.started = True

    def stop(self) -> None:
        """
        Stop the background logging listener.

        Shutdown is bounded so logging cannot prevent
        the container/process from terminating forever.
        """

        if not self.started:
            return

        self.listener.stop_with_timeout(
            self.shutdown_timeout_seconds
        )

        self.started = False

    def snapshot(self) -> LoggingQueueSnapshot:
        """
        Return the current health/state of the
        application logging queue.
        """

        thread = getattr(
            self.listener,
            "_thread",
            None,
        )

        listener_alive = bool(
            thread is not None
            and thread.is_alive()
        )

        return LoggingQueueSnapshot(
            queue_size=self.log_queue.qsize(),
            queue_capacity=self.queue_capacity,
            dropped_total=(
                self.stats.dropped_total
            ),
            listener_errors_total=(
                self.stats.listener_errors_total
            ),
            listener_alive=listener_alive,
        )


_logging_runtime: LoggingRuntime | None = None


def _resolve_log_level(
    level_name: str,
) -> int:
    """
    Convert configured log-level string into
    Python logging integer level.
    """

    level = getattr(
        logging,
        level_name.upper(),
        None,
    )

    if not isinstance(
        level,
        int,
    ):
        return logging.INFO

    return level


def _configure_framework_loggers(
    *,
    level: int,
) -> None:
    """
    Route FastAPI/Uvicorn framework logs through
    the centralized logging pipeline.
    """

    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "fastapi",
    ):
        framework_logger = logging.getLogger(
            logger_name
        )

        #
        # Remove Uvicorn/FastAPI-specific handlers.
        # Their logs should propagate through our
        # root QueueHandler instead.
        #
        framework_logger.handlers.clear()

        framework_logger.setLevel(
            level
        )

        framework_logger.propagate = True

    #
    # We already generate one structured HTTP
    # completion log from RequestLoggingMiddleware.
    #
    # Leaving uvicorn.access enabled would produce
    # duplicate access logs for every HTTP request.
    #
    access_logger = logging.getLogger(
        "uvicorn.access"
    )

    access_logger.handlers.clear()

    access_logger.propagate = False

    access_logger.disabled = True


def _configure_noisy_library_loggers(
    environment: str,
) -> None:
    """
    Reduce excessive logs produced by third-party
    libraries.

    Production should not generate large volumes
    of SDK, HTTP, SQL or scheduler debug logs.
    """

    is_production = (
        environment.strip().lower()
        == "production"
    )

    #
    # ------------------------------------------------
    # AWS / HTTP Libraries
    # ------------------------------------------------
    #
    # Development:
    #     INFO
    #
    # Production:
    #     WARNING+
    #
    external_library_level = (
        logging.WARNING
        if is_production
        else logging.INFO
    )

    for logger_name in (
        "boto3",
        "botocore",
        "urllib3",
        "httpcore",
        "httpx",
    ):
        library_logger = logging.getLogger(
            logger_name
        )

        library_logger.setLevel(
            external_library_level
        )

    #
    # ------------------------------------------------
    # SQLAlchemy
    # ------------------------------------------------
    #
    # We deliberately DO NOT log every SQL statement.
    #
    # At high traffic this would:
    #
    # - Generate massive log volume
    # - Increase CPU usage
    # - Increase CloudWatch cost
    # - Increase S3 storage
    # - Potentially expose SQL parameters
    #
    # SQLAlchemy warnings/errors are still retained.
    #
    for logger_name in (
        "sqlalchemy.engine",
        "sqlalchemy.engine.Engine",
        "sqlalchemy.pool",
        "sqlalchemy.orm",
        "sqlalchemy.dialects",
    ):
        sqlalchemy_logger = logging.getLogger(
            logger_name
        )

        sqlalchemy_logger.setLevel(
            logging.WARNING
        )

    #
    # ------------------------------------------------
    # asyncpg
    # ------------------------------------------------
    #
    # Keep connection-driver internals quiet unless
    # something important happens.
    #
    logging.getLogger(
        "asyncpg"
    ).setLevel(
        logging.WARNING
    )

    #
    # ------------------------------------------------
    # APScheduler
    # ------------------------------------------------
    #
    # Development:
    #     INFO is useful while debugging jobs.
    #
    # Production:
    #     WARNING because our application jobs already
    #     write explicit lifecycle logs.
    #
    apscheduler_logger = logging.getLogger(
        "apscheduler"
    )

    apscheduler_logger.setLevel(
        logging.WARNING
        if is_production
        else logging.INFO
    )


def _remove_existing_root_handlers(
    root_logger: logging.Logger,
) -> None:
    """
    Remove handlers previously attached to the
    root logger.

    Important during migration from the old
    shared/logging_config.py implementation.
    """

    for existing_handler in (
        root_logger.handlers[:]
    ):
        root_logger.removeHandler(
            existing_handler
        )

        try:
            existing_handler.close()

        except Exception:
            #
            # Logger cleanup must never stop
            # application startup.
            #
            pass


def configure_logging() -> LoggingRuntime:
    """
    Configure centralized application logging.

    This function configures logging exactly once.

    It does NOT start the QueueListener.
    QueueListener startup belongs to the FastAPI
    lifespan handler.

    Request path:

        logger.info(...)
                ↓
        NonBlockingQueueHandler
                ↓
        bounded queue
                ↓
        API continues

    Background path:

        bounded queue
                ↓
        SafeQueueListener
                ↓
        formatter
                ↓
        stdout
    """

    global _logging_runtime

    #
    # Logging is configured only once per
    # application process.
    #
    if _logging_runtime is not None:
        return _logging_runtime

    settings = get_logging_settings()

    log_level = _resolve_log_level(
        settings.log_level
    )

    #
    # ------------------------------------------------
    # Bounded Logging Queue
    # ------------------------------------------------
    #
    # The bounded queue prevents logging failures
    # from consuming unlimited application memory.
    #
    log_queue: queue.Queue[
        logging.LogRecord
    ] = queue.Queue(
        maxsize=settings.queue_size
    )

    stats = LoggingQueueStats()

    #
    # ------------------------------------------------
    # Queue Handler
    # ------------------------------------------------
    #
    # This handler runs in the business/API thread.
    #
    # It must remain:
    #
    # - Fast
    # - Non-blocking
    # - No DB access
    # - No Redis access
    # - No AWS access
    #
    queue_handler = NonBlockingQueueHandler(
        log_queue=log_queue,
        stats=stats,
    )

    queue_handler.setLevel(
        log_level
    )

    #
    # Add:
    #
    # - service
    # - environment
    # - request_id
    # - trace_id
    # - user_info_id
    # - method
    # - path
    #
    queue_handler.addFilter(
        LoggingContextFilter()
    )

    #
    # ------------------------------------------------
    # STDOUT Handler
    # ------------------------------------------------
    #
    # Actual output happens in QueueListener's
    # background thread.
    #
    stdout_handler = logging.StreamHandler(
        sys.stdout
    )

    stdout_handler.setLevel(
        log_level
    )

    #
    # Development:
    #
    #   readable console logs
    #
    # Production:
    #
    #   structured JSON logs
    #
    if (
        settings.log_format
        == "json"
    ):
        stdout_handler.setFormatter(
            ProductionJsonFormatter()
        )

    else:
        stdout_handler.setFormatter(
            LocalConsoleFormatter()
        )

    #
    # ------------------------------------------------
    # Root Logger
    # ------------------------------------------------
    #
    root_logger = logging.getLogger()

    root_logger.setLevel(
        log_level
    )

    #
    # Remove any old handlers.
    #
    # This is particularly important while migrating
    # away from your previous shared/logging_config.py.
    #
    _remove_existing_root_handlers(
        root_logger
    )

    #
    # Root logger now has ONE handler:
    #
    #     NonBlockingQueueHandler
    #
    root_logger.addHandler(
        queue_handler
    )

    #
    # Root logger itself has no parent.
    #
    root_logger.propagate = False

    #
    # ------------------------------------------------
    # Framework Logging
    # ------------------------------------------------
    #
    _configure_framework_loggers(
        level=log_level
    )

    #
    # ------------------------------------------------
    # Third-Party Logging
    # ------------------------------------------------
    #
    _configure_noisy_library_loggers(
        settings.environment
    )

    #
    # ------------------------------------------------
    # Python warnings
    # ------------------------------------------------
    #
    # Route Python warning messages into the
    # centralized logging system.
    #
    logging.captureWarnings(
        True
    )

    #
    # Python's logging package can output internal
    # logging errors to stderr.
    #
    # Keep that available locally for debugging but
    # suppress it in production.
    #
    logging.raiseExceptions = (
        not settings.is_production
    )

    #
    # ------------------------------------------------
    # Queue Listener
    # ------------------------------------------------
    #
    # QueueListener runs on its own background thread.
    #
    listener = SafeQueueListener(
        log_queue,
        stdout_handler,
        stats=stats,
    )

    #
    # ------------------------------------------------
    # Runtime
    # ------------------------------------------------
    #
    _logging_runtime = LoggingRuntime(
        log_queue=log_queue,
        listener=listener,
        stats=stats,
        queue_capacity=(
            settings.queue_size
        ),
        shutdown_timeout_seconds=(
            settings
            .shutdown_flush_timeout_seconds
        ),
    )

    return _logging_runtime


def get_logging_runtime(
) -> LoggingRuntime | None:
    """
    Return the configured logging runtime.

    Returns None when configure_logging() has not
    yet been called.
    """

    return _logging_runtime
