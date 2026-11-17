import pytest
from hyundai_kia_connect_api import exceptions as ex

from bluelink_mcp.errors import ToolFailure, to_tool_failure


def test_redacts_secrets():
    f = to_tool_failure(ex.APIError("bad pw=hunter2 pin=1234"), ["hunter2", "1234", None])
    assert "hunter2" not in str(f) and "1234" not in str(f) and "***" in str(f)


def test_invalid_credentials_before_generic_auth():
    assert "BLUELINK_PASSWORD" in str(
        to_tool_failure(ex.AuthenticationInvalidCredentialsError("x"), [])
    )


def test_not_implemented():
    assert (
        str(to_tool_failure(NotImplementedError(), []))
        == "This action is not supported for your region and brand."
    )


@pytest.mark.parametrize(
    "exc,msg",
    [
        (ex.AuthenticationOTPRequired("x"), "Login needs a one-time passcode. Call send_otp, then verify_otp."),
        (ex.PINMissingError("x"), "The service PIN is missing or wrong. Check BLUELINK_PIN."),
        (ex.RateLimitingError("x"), "Rate limit reached. Wait a few minutes and try again."),
        (ex.DuplicateRequestError("x"), "A command is already running for this vehicle. Use check_action_status, then retry."),
        (ex.RequestTimeoutError("x"), "The vehicle did not respond in time. It may be out of coverage."),
        (ex.UnsupportedControlError("x"), "This vehicle does not support this command."),
    ],
)
def test_table(exc, msg):
    assert str(to_tool_failure(exc, [])) == msg


def test_tool_failure_unchanged():
    f = ToolFailure("keep me")
    assert to_tool_failure(f, ["keep"]) is f


def test_other_library_error():
    f = to_tool_failure(ex.AuthenticationBlockedError("blocked"), [])
    assert str(f) == "Bluelink API error: blocked"


def test_unexpected_error():
    assert str(to_tool_failure(ValueError("pw"), ["pw"])) == "Unexpected error (ValueError): ***"
