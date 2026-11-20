from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


_request_id_var: ContextVar[str | None] = ContextVar(
    "logging_request_id",
    default=None,
)

_user_info_id_var: ContextVar[int | None] = ContextVar(
    "logging_user_info_id",
    default=None,
)

_trace_id_var: ContextVar[str | None] = ContextVar(
    "logging_trace_id",
    default=None,
)

_http_method_var: ContextVar[str | None] = ContextVar(
    "logging_http_method",
    default=None,
)

_http_path_var: ContextVar[str | None] = ContextVar(
    "logging_http_path",
    default=None,
)


@dataclass(frozen=True)
class RequestContextTokens:
    """
    Tokens used to safely restore ContextVar values
    after an HTTP request finishes.
    """

    request_id: Any
    user_info_id: Any
    trace_id: Any
    method: Any
    path: Any


def bind_request_context(
    *,
    request_id: str,
    method: str,
    path: str,
    trace_id: str | None = None,
) -> RequestContextTokens:
    """
    Bind request-scoped values.

    Called once by the HTTP logging middleware.
    """

    return RequestContextTokens(
        request_id=_request_id_var.set(
            request_id
        ),
        user_info_id=_user_info_id_var.set(
            None
        ),
        trace_id=_trace_id_var.set(
            trace_id
        ),
        method=_http_method_var.set(
            method
        ),
        path=_http_path_var.set(
            path
        ),
    )


def set_user_info_id(
    user_info_id: int | None,
) -> None:
    """
    Attach authenticated user ID to the current
    request logging context.
    """

    _user_info_id_var.set(
        user_info_id
    )


def set_trace_id(
    trace_id: str | None,
) -> None:
    """Attach distributed trace ID."""

    _trace_id_var.set(
        trace_id
    )


def set_request_path(
    path: str,
) -> None:
    """
    Replace raw URL path with the resolved route path.

    Example:
        /parents/123
        becomes
        /parents/{parent_id}
    """

    _http_path_var.set(
        path
    )


def get_logging_context() -> dict[str, Any]:
    """Return current request logging metadata."""

    return {
        "request_id": _request_id_var.get(),
        "user_info_id": _user_info_id_var.get(),
        "trace_id": _trace_id_var.get(),
        "method": _http_method_var.get(),
        "path": _http_path_var.get(),
    }


def reset_request_context(
    tokens: RequestContextTokens,
) -> None:
    """
    Restore ContextVars to their values before
    the request started.

    This prevents context leaking between requests.
    """

    # Reverse order is intentional.
    _http_path_var.reset(
        tokens.path
    )

    _http_method_var.reset(
        tokens.method
    )

    _trace_id_var.reset(
        tokens.trace_id
    )

    _user_info_id_var.reset(
        tokens.user_info_id
    )

    _request_id_var.reset(
        tokens.request_id
    )


def clear_logging_context() -> None:
    """
    Clear logging context manually.

    Useful for background jobs when request middleware
    is not involved.
    """

    _request_id_var.set(None)
    _user_info_id_var.set(None)
    _trace_id_var.set(None)
    _http_method_var.set(None)
    _http_path_var.set(None)
