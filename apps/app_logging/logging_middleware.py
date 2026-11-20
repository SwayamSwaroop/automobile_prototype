from __future__ import annotations

import logging
import time
import uuid

from starlette.datastructures import (
    Headers,
    MutableHeaders,
)
from starlette.types import (
    ASGIApp,
    Message,
    Receive,
    Scope,
    Send,
)

from apps.app_logging.logging_config import (
    get_logging_settings,
)
from apps.app_logging.logging_context import (
    bind_request_context,
    reset_request_context,
    set_request_path,
)


logger = logging.getLogger(
    __name__
)


def _resolve_request_id(
    scope: Scope,
) -> str:
    """
    Reuse incoming X-Request-ID only when it is
    a valid UUID.

    Otherwise generate a server-side request ID.
    """

    try:
        headers = Headers(
            scope=scope
        )

        incoming_request_id = (
            headers.get(
                "x-request-id"
            )
        )

        if incoming_request_id:
            parsed = uuid.UUID(
                incoming_request_id
            )

            return str(
                parsed
            )

    except Exception:
        pass

    return str(
        uuid.uuid4()
    )


def _resolve_trace_id(
    scope: Scope,
) -> str | None:
    """
    Pick up an existing infrastructure trace header
    when available.

    No distributed tracing system is required yet.
    """

    try:
        headers = Headers(
            scope=scope
        )

        trace_id = (
            headers.get(
                "x-amzn-trace-id"
            )
            or headers.get(
                "traceparent"
            )
        )

        if not trace_id:
            return None

        #
        # Prevent unbounded user-controlled header
        # values from entering logs.
        #
        return trace_id[:256]

    except Exception:
        return None


def _resolve_route_path(
    scope: Scope,
) -> str:
    """
    Return canonical API route including application
    root_path.

    Example:
        root_path = /api
        route.path = /auth/login

    Result:
        /api/auth/login
    """

    route = scope.get("route")

    route_path = getattr(
        route,
        "path",
        None,
    )

    if not route_path:
        return str(
            scope.get(
                "path",
                "",
            )
        )

    root_path = str(
        scope.get(
            "root_path",
            "",
        )
    ).rstrip("/")

    route_path = str(
        route_path
    )

    if not root_path:
        return route_path

    return (
        f"{root_path}/"
        f"{route_path.lstrip('/')}"
    )


class RequestLoggingMiddleware:
    """
    Request correlation and HTTP telemetry.

    Does not read request or response bodies.
    """

    def __init__(
        self,
        app: ASGIApp,
    ) -> None:
        self.app = app

        settings = (
            get_logging_settings()
        )

        self._slow_threshold_ms = (
            settings
            .slow_request_threshold_ms
        )

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"]
            != "http"
        ):
            await self.app(
                scope,
                receive,
                send,
            )

            return

        request_id = (
            _resolve_request_id(
                scope
            )
        )

        trace_id = (
            _resolve_trace_id(
                scope
            )
        )

        method = str(
            scope.get(
                "method",
                "UNKNOWN",
            )
        )

        initial_path = str(
            scope.get(
                "path",
                "",
            )
        )

        context_tokens = (
            bind_request_context(
                request_id=request_id,
                method=method,
                path=initial_path,
                trace_id=trace_id,
            )
        )

        started_at = (
            time.perf_counter()
        )

        status_code = 500

        async def send_wrapper(
            message: Message,
        ) -> None:
            nonlocal status_code

            if (
                message["type"]
                == "http.response.start"
            ):
                status_code = int(
                    message["status"]
                )

                headers = (
                    MutableHeaders(
                        scope=message
                    )
                )

                headers[
                    "X-Request-ID"
                ] = request_id

            await send(
                message
            )

        try:
            await self.app(
                scope,
                receive,
                send_wrapper,
            )

        except Exception:
            duration_ms = round(
                (
                    time.perf_counter()
                    - started_at
                )
                * 1000,
                2,
            )

            route_path = (
                _resolve_route_path(
                    scope
                )
            )

            set_request_path(
                route_path
            )

            logger.exception(
                "Unhandled HTTP request exception",
                extra={
                    "event": (
                        "HTTP_REQUEST_FAILED"
                    ),
                    "category": "HTTP",
                    "status_code": 500,
                    "duration_ms": (
                        duration_ms
                    ),
                },
            )

            raise

        else:
            duration_ms = round(
                (
                    time.perf_counter()
                    - started_at
                )
                * 1000,
                2,
            )

            route_path = (
                _resolve_route_path(
                    scope
                )
            )

            set_request_path(
                route_path
            )

            is_slow = (
                duration_ms
                >= self._slow_threshold_ms
            )

            extra = {
                "category": "HTTP",
                "status_code": (
                    status_code
                ),
                "duration_ms": (
                    duration_ms
                ),
            }

            if status_code >= 500:
                extra["event"] = (
                    "HTTP_REQUEST_FAILED"
                )

                logger.error(
                    "HTTP request completed "
                    "with server error",
                    extra=extra,
                )

            elif is_slow:
                extra["event"] = (
                    "HTTP_SLOW_REQUEST"
                )

                logger.warning(
                    "Slow HTTP request",
                    extra=extra,
                )

            else:
                extra["event"] = (
                    "HTTP_REQUEST_COMPLETED"
                )

                logger.info(
                    "HTTP request completed",
                    extra=extra,
                )

        finally:
            reset_request_context(
                context_tokens
            )
