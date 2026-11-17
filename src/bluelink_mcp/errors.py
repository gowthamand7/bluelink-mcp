from __future__ import annotations

from collections.abc import Sequence

from hyundai_kia_connect_api import exceptions as ex
from mcp.server.fastmcp.exceptions import ToolError


class ToolFailure(ToolError):
    """A safe, user-facing error message."""


# Most specific first: subclasses must precede their parents.
_MESSAGES: list[tuple[type[BaseException], str]] = [
    (
        ex.AuthenticationOTPRequired,
        "Login needs a one-time passcode. Call send_otp, then verify_otp.",
    ),
    (
        ex.AuthenticationInvalidCredentialsError,
        "Login failed. Check BLUELINK_USERNAME and BLUELINK_PASSWORD.",
    ),
    (ex.PINMissingError, "The service PIN is missing or wrong. Check BLUELINK_PIN."),
    (ex.RateLimitingError, "Rate limit reached. Wait a few minutes and try again."),
    (
        ex.DuplicateRequestError,
        "A command is already running for this vehicle. Use check_action_status, then retry.",
    ),
    (
        ex.RequestTimeoutError,
        "The vehicle did not respond in time. It may be out of coverage.",
    ),
    (ex.UnsupportedControlError, "This vehicle does not support this command."),
    (
        NotImplementedError,
        "This action is not supported for your region and brand.",
    ),
]


def _redact(text: str, secrets: Sequence[str | None]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def to_tool_failure(exc: BaseException, secrets: Sequence[str | None]) -> ToolFailure:
    if isinstance(exc, ToolFailure):
        return exc
    for exc_type, message in _MESSAGES:
        if isinstance(exc, exc_type):
            return ToolFailure(message)
    detail = _redact(str(exc), secrets)
    if isinstance(exc, ex.HyundaiKiaException):
        return ToolFailure(f"Bluelink API error: {detail}")
    return ToolFailure(f"Unexpected error ({type(exc).__name__}): {detail}")
