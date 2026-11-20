from __future__ import annotations

import logging

from apps.app_logging.logging_config import (
    get_logging_settings,
)
from apps.app_logging.logging_context import (
    get_logging_context,
)


class LoggingContextFilter(logging.Filter):
    """
    Add application and request context to every log.

    IMPORTANT:
    This filter must never perform:
    - Database calls
    - Redis calls
    - HTTP calls
    - AWS calls
    - File I/O
    """

    def __init__(self) -> None:
        super().__init__()

        settings = get_logging_settings()

        self._service = (
            settings.app_name
        )

        self._environment = (
            settings.environment
        )

    def filter(
        self,
        record: logging.LogRecord,
    ) -> bool:
        """
        Enrich the LogRecord.

        Logging metadata failure must never break
        a business API.
        """

        try:
            if not hasattr(
                record,
                "service",
            ):
                record.service = (
                    self._service
                )

            if not hasattr(
                record,
                "environment",
            ):
                record.environment = (
                    self._environment
                )

            context = (
                get_logging_context()
            )

            for key, value in (
                context.items()
            ):
                if not hasattr(
                    record,
                    key,
                ):
                    setattr(
                        record,
                        key,
                        value,
                    )

        except Exception:
            # Intentional fail-open behavior.
            #
            # Context enrichment must never cause
            # API failure.
            pass

        return True
