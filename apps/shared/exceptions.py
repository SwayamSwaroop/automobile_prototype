import json
import logging
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code: int = 400
    code: str = "APP_ERROR"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        data: Any = None,
        already_logged: bool = False,
    ) -> None:
        super().__init__(message)

        self.message = message
        self.data = data

        #
        # True:
        # Router/service already created a meaningful
        # domain log for this exception.
        #
        # False:
        # Global exception handler should create the
        # fallback application-error log.
        #
        self.already_logged = already_logged

        if status_code is not None:
            self.status_code = status_code

        if code is not None:
            self.code = code


class BadRequestApp(AppError):
    def __init__(
        self,
        message: str = "Bad request",
    ) -> None:
        super().__init__(
            message,
            status_code=400,
            code="BAD_REQUEST",
        )


class UnauthorizedError(AppError):
    def __init__(
        self,
        message: str = "Unauthorized",
        *,
        status_code: int = 401,
        data: Any = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code="UNAUTHORIZED",
            data=data,
        )


class ValidationErrorApp(AppError):
    def __init__(
        self,
        message: str = "Validation failed",
        data: Any = None,
    ) -> None:
        super().__init__(
            message,
            status_code=422,
            code="VALIDATION_ERROR",
            data=data,
        )


class ConflictError(AppError):
    def __init__(
        self,
        message: str = "Conflict",
        *,
        status_code: int = 409,
        data: Any = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code="CONFLICT",
            data=data,
        )


class ForbiddenError(AppError):
    def __init__(
        self,
        message: str = "Forbidden",
    ) -> None:
        super().__init__(
            message,
            status_code=403,
            code="FORBIDDEN",
        )


class NotFoundError(AppError):
    def __init__(
        self,
        message: str = "Not found",
        *,
        status_code: int = 404,
        data: Any = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code="NOT_FOUND",
            data=data,
        )


class FileSaveError(AppError):
    def __init__(
        self,
        message: str = "Failed to save file",
    ) -> None:
        super().__init__(
            message,
            status_code=500,
            code="FILE_SAVE_ERROR",
        )


def _safe_validation_errors(
    errors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    safe: list[dict[str, str]] = []

    for err in errors:
        current = dict(err)

        ctx = current.get("ctx")

        if (
            isinstance(ctx, dict)
            and ctx.get("error") is not None
        ):
            ctx["error"] = str(
                ctx["error"]
            )

            current["ctx"] = ctx

        if "input" in current:
            try:
                json.dumps(
                    current["input"]
                )

            except Exception:
                current["input"] = str(
                    current["input"]
                )

        loc = current.get(
            "loc",
            [],
        )

        field = ".".join(
            str(item)
            for item in loc
            if item != "body"
        )

        message = current.get(
            "msg",
            "Invalid input",
        )

        if (
            isinstance(message, str)
            and message.startswith(
                "Value error, "
            )
        ):
            message = message.replace(
                "Value error, ",
                "",
                1,
            )

        safe.append(
            {
                "field": field,
                "message": str(message),
            }
        )

    return safe


def register_exception_handlers(
    app,
) -> None:

    # -------------------------------------------------
    # Application Errors
    # -------------------------------------------------

    @app.exception_handler(AppError)
    async def app_error_handler(
        request: Request,
        exc: AppError,
    ):
        """
        Handle expected application/business errors.

        If the router/service already produced a
        meaningful domain log, do not log the same
        exception again here.

        Legacy APIs that do not log the AppError
        themselves still receive a fallback log.
        """

        if not exc.already_logged:

            log_level = (
                logging.ERROR
                if exc.status_code >= 500
                else logging.WARNING
            )

            logger.log(
                log_level,
                "Application error",
                extra={
                    "event": "APP_ERROR",
                    "category": "APPLICATION",
                    "error_code": exc.code,
                    "status_code": (
                        exc.status_code
                    ),
                },
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "message": exc.message,
                "data": exc.data,
                "code": exc.code,
            },
        )

    # -------------------------------------------------
    # Database Integrity Errors
    # -------------------------------------------------

    @app.exception_handler(
        IntegrityError
    )
    async def integrity_error_handler(
        request: Request,
        exc: IntegrityError,
    ):
        logger.warning(
            "Database integrity error",
            extra={
                "event": (
                    "DATABASE_INTEGRITY_ERROR"
                ),
                "category": "DATABASE",
                "status_code": 409,
            },
        )

        return JSONResponse(
            status_code=409,
            content={
                "message": (
                    "Duplicate or constraint "
                    "violation."
                ),
                "data": None,
                "code": "CONFLICT",
            },
        )

    # -------------------------------------------------
    # FastAPI / Pydantic Validation Errors
    # -------------------------------------------------

    @app.exception_handler(
        RequestValidationError
    )
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ):
        errors = _safe_validation_errors(
            exc.errors()
        )

        first_message = (
            errors[0]["message"]
            if errors
            else "Validation failed"
        )

        return JSONResponse(
            status_code=422,
            content={
                "message": first_message,
                "data": errors,
                "code": "VALIDATION_ERROR",
            },
        )

    # -------------------------------------------------
    # FastAPI HTTP Exceptions
    # -------------------------------------------------

    @app.exception_handler(
        HTTPException
    )
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ):
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "VALIDATION_ERROR",
        }

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "message": (
                    str(exc.detail)
                    if exc.detail
                    else "HTTP error"
                ),
                "data": None,
                "code": code_map.get(
                    exc.status_code,
                    "HTTP_ERROR",
                ),
            },
        )

    # -------------------------------------------------
    # Completely Unhandled Exceptions
    # -------------------------------------------------

    @app.exception_handler(
        Exception
    )
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ):
        logger.critical(
            "Unhandled application error",
            exc_info=(
                type(exc),
                exc,
                exc.__traceback__,
            ),
            extra={
                "event": (
                    "UNHANDLED_APPLICATION_ERROR"
                ),
                "category": "APPLICATION",
                "status_code": 500,
            },
        )

        return JSONResponse(
            status_code=500,
            content={
                "message": (
                    "Internal Server Error"
                ),
                "data": None,
                "code": (
                    "INTERNAL_SERVER_ERROR"
                ),
            },
        )
