from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


SENSITIVE_KEYS = {
    "password",
    "confirm_password",
    "current_password",
    "new_password",

    "access_token",
    "refresh_token",
    "id_token",

    "authorization",
    "proxy_authorization",

    "cookie",
    "set_cookie",

    "otp",
    "pin",

    "secret",
    "client_secret",

    "api_key",
    "apikey",

    "aws_access_key_id",
    "aws_secret_access_key",

    "cognito_app_secret_key",

    "razorpay_signature",
    "razorpay_secret",

    # Looks like a digest, behaves like a credential: the reset flow
    # looks the OTP record up BY this hash, so anyone holding it can
    # complete a password/PIN reset.
    "reset_token_hash",
    "verification_token_hash",
}


#
# Keys whose value is reduced rather than removed.
#
# Redaction is right for a credential: the value has no diagnostic
# use, so blanking it costs nothing.
#
# An identifier is different. Pre-authentication flows (login,
# signup, OTP, forgot-password) have no user_info_id yet, so the
# email is the ONLY handle on "why can't this particular parent get
# in?". Blanking it would make those flows undebuggable.
#
# Masking keeps the domain and the shape - enough to match a support
# ticket or spot a typo'd domain - while storing nothing that
# identifies a person.
#
EMAIL_KEYS = {
    "email",
    "username",
}

EMAIL_KEY_SUFFIXES = (
    "_email",
)


#
# Provider-side identifiers. Opaque and non-human-readable, but still
# a stable per-person handle, so the tail is kept for correlation with
# the provider console and the rest is dropped.
#
OPAQUE_ID_KEYS = {
    "cognito_sub",
}


STANDARD_LOG_RECORD_FIELDS = set(
    logging.makeLogRecord(
        {}
    ).__dict__.keys()
)

STANDARD_LOG_RECORD_FIELDS.update(
    {
        "message",
        "asctime",
    }
)


CORE_CUSTOM_FIELDS = {
    "service",
    "environment",
    "event",
    "category",

    "request_id",
    "trace_id",
    "user_info_id",

    "method",
    "path",
}


def _normalize_key(
    key: str,
) -> str:
    return (
        key.strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _is_sensitive_key(
    key: str,
) -> bool:
    normalized = _normalize_key(
        key
    )

    if normalized in SENSITIVE_KEYS:
        return True

    sensitive_suffixes = (
        "_password",
        "_secret",
        "_token",
        "_api_key",
        "_signature",
    )

    return normalized.endswith(
        sensitive_suffixes
    )


def _already_masked(
    value: Any,
) -> bool:
    """
    True when a value already carries a mask marker.
    """

    return (
        isinstance(
            value,
            str,
        )
        and value.startswith(
            "***"
        )
    )


def _mask_email(
    value: Any,
) -> Any:
    """
    "parent@example.com" -> "p***t@example.com"

    Non-string or non-email values fall through to
    opaque masking rather than being trusted.
    """

    if not isinstance(
        value,
        str,
    ):
        return "***MASKED***"

    if _already_masked(
        value
    ):
        #
        # format() sanitizes log_data a second time
        # after building it, so every masker has to be
        # idempotent or the mask itself gets re-masked.
        #
        return value

    local, at, domain = (
        value.rpartition("@")
    )

    if (
        not at
        or not local
        or not domain
    ):
        #
        # Cognito usernames are not always emails.
        #
        return _mask_opaque_id(
            value
        )

    if len(local) == 1:
        return f"*@{domain}"

    if len(local) == 2:
        return (
            f"{local[0]}*@{domain}"
        )

    return (
        f"{local[0]}***{local[-1]}"
        f"@{domain}"
    )


def _mask_opaque_id(
    value: Any,
) -> Any:
    """
    Keep only the tail, enough to correlate a record
    without identifying its owner.
    """

    if _already_masked(
        value
    ):
        return value

    try:
        text = str(
            value
        )

    except Exception:
        return "***MASKED***"

    if len(text) <= 4:
        return "***MASKED***"

    return f"***{text[-4:]}"


def _masker_for(
    key: str,
):
    """
    Return the masking function for a key, or None
    when the value may be logged as-is.
    """

    normalized = _normalize_key(
        key
    )

    if (
        normalized in EMAIL_KEYS
        or normalized.endswith(
            EMAIL_KEY_SUFFIXES
        )
    ):
        return _mask_email

    if normalized in OPAQUE_ID_KEYS:
        return _mask_opaque_id

    return None


def _sanitize_value(
    value: Any,
) -> Any:
    """
    Recursively redact sensitive dictionary fields.

    This runs in the listener thread instead of the
    request thread.
    """

    if isinstance(
        value,
        Mapping,
    ):
        result: dict[str, Any] = {}

        for raw_key, raw_value in (
            value.items()
        ):
            key = str(
                raw_key
            )

            if _is_sensitive_key(
                key
            ):
                result[key] = (
                    "***REDACTED***"
                )

                continue

            masker = _masker_for(
                key
            )

            if masker is not None:
                result[key] = masker(
                    raw_value
                )

                continue

            result[key] = (
                _sanitize_value(
                    raw_value
                )
            )

        return result

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return [
            _sanitize_value(
                item
            )
            for item in value
        ]

    return value


class ProductionJsonFormatter(
    logging.Formatter
):
    """Production structured JSON formatter."""

    def format(
        self,
        record: logging.LogRecord,
    ) -> str:
        try:
            message = (
                record.getMessage()
            )

        except Exception:
            message = (
                "<unable to format log message>"
            )

        timestamp = (
            datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            )
            .isoformat(
                timespec="milliseconds"
            )
            .replace(
                "+00:00",
                "Z",
            )
        )

        log_data: dict[str, Any] = {
            "timestamp": timestamp,

            "level": (
                record.levelname
            ),

            "service": getattr(
                record,
                "service",
                None,
            ),

            "environment": getattr(
                record,
                "environment",
                None,
            ),

            "event": getattr(
                record,
                "event",
                None,
            ),

            "category": getattr(
                record,
                "category",
                None,
            ),

            "logger": (
                record.name
            ),

            "message": message,

            "request_id": getattr(
                record,
                "request_id",
                None,
            ),

            "trace_id": getattr(
                record,
                "trace_id",
                None,
            ),

            "user_info_id": getattr(
                record,
                "user_info_id",
                None,
            ),

            "method": getattr(
                record,
                "method",
                None,
            ),

            "path": getattr(
                record,
                "path",
                None,
            ),
        }

        #
        # Include custom "extra={}" values such as:
        #
        # status_code
        # duration_ms
        # worksheet_id
        # subscription_id
        #
        for key, value in (
            record.__dict__.items()
        ):
            if (
                key
                in STANDARD_LOG_RECORD_FIELDS
            ):
                continue

            if key in CORE_CUSTOM_FIELDS:
                continue

            if key.startswith("_"):
                continue

            if _is_sensitive_key(
                key
            ):
                log_data[key] = (
                    "***REDACTED***"
                )

                continue

            masker = _masker_for(
                key
            )

            if masker is not None:
                log_data[key] = masker(
                    value
                )

                continue

            log_data[key] = (
                _sanitize_value(
                    value
                )
            )

        if record.exc_info:
            try:
                log_data["exception"] = (
                    self.formatException(
                        record.exc_info
                    )
                )

            except Exception:
                log_data[
                    "exception"
                ] = (
                    "<unable to format "
                    "exception>"
                )

        if record.stack_info:
            log_data["stack_info"] = (
                record.stack_info
            )

        #
        # Remove empty optional fields.
        #
        log_data = {
            key: value
            for key, value
            in log_data.items()
            if value is not None
        }

        log_data = _sanitize_value(
            log_data
        )

        try:
            return json.dumps(
                log_data,
                ensure_ascii=False,
                default=str,
                separators=(
                    ",",
                    ":",
                ),
            )

        except Exception:
            #
            # Formatter itself should fail safely.
            #
            fallback = {
                "timestamp": timestamp,
                "level": (
                    record.levelname
                ),
                "logger": (
                    record.name
                ),
                "message": (
                    "<log serialization failed>"
                ),
            }

            return json.dumps(
                fallback,
                separators=(
                    ",",
                    ":",
                ),
            )


class LocalConsoleFormatter(
    logging.Formatter
):
    """Readable formatter for local development."""

    def format(
        self,
        record: logging.LogRecord,
    ) -> str:
        timestamp = (
            datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            )
            .isoformat(
                timespec="milliseconds"
            )
            .replace(
                "+00:00",
                "Z",
            )
        )

        try:
            message = (
                record.getMessage()
            )

        except Exception:
            message = (
                "<unable to format log message>"
            )

        parts = [
            timestamp,
            record.levelname,
            record.name,
        ]

        event = getattr(
            record,
            "event",
            None,
        )

        request_id = getattr(
            record,
            "request_id",
            None,
        )

        if event:
            parts.append(
                f"event={event}"
            )

        if request_id:
            parts.append(
                f"request_id={request_id}"
            )

        parts.append(
            message
        )

        output = " | ".join(
            parts
        )

        if record.exc_info:
            try:
                output += (
                    "\n"
                    + self.formatException(
                        record.exc_info
                    )
                )

            except Exception:
                pass

        return output
