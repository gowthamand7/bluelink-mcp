import asyncio

import pytest
from hyundai_kia_connect_api.ApiImpl import OTPRequest
from hyundai_kia_connect_api.const import OTP_NOTIFY_TYPE
from hyundai_kia_connect_api.exceptions import APIError
from hyundai_kia_connect_api.Vehicle import Vehicle

from bluelink_mcp.errors import ToolFailure
from bluelink_mcp.session import Session
from bluelink_mcp.token_store import load_token, save_token
from fakes import FakeFactory, FakeManager, make_token


def _otp():
    return OTPRequest(None, None, True, True, None, None)


async def test_loads_saved_token_into_factory(config):
    save_token(config, make_token("saved"))
    f = FakeFactory()
    await Session(config, f).call(lambda m: None)
    assert f.received_token.access_token == "saved"


async def test_no_saved_token_passes_none(config):
    f = FakeFactory()
    await Session(config, f).call(lambda m: None)
    assert f.received_token is None


async def test_saves_token_when_it_changes(config):
    def swap(m):
        m.token = make_token("new")

    f = FakeFactory(FakeManager(make_token("old")))
    f.manager.refresh_effect = swap
    await Session(config, f).call(lambda m: None)
    assert load_token(config).access_token == "new"


async def test_does_not_save_when_unchanged(config):
    save_token(config, make_token("same"))
    mtime = config.token_path.stat().st_mtime_ns
    await Session(config, FakeFactory()).call(lambda m: None)
    assert config.token_path.stat().st_mtime_ns == mtime


async def test_returns_fn_result(config):
    assert await Session(config, FakeFactory()).call(lambda m: 42) == 42


async def test_unknown_vehicle_id(config):
    s = Session(config, FakeFactory())
    with pytest.raises(ToolFailure, match="Call list_vehicles"):
        await s.call(lambda m: s.vehicle(m, "nope"))


async def test_known_vehicle_id(config):
    f = FakeFactory()
    f.manager.vehicles = {"v1": "car"}
    s = Session(config, f)
    assert await s.call(lambda m: s.vehicle(m, "v1")) == "car"


async def test_vehicle_resolves_public_vin_id_and_library_id(config):
    car = Vehicle(id="H0000000000KMHXX00XXXX123456", name="2022 TESTCAR", VIN="KMHXX00XXXX123456")
    f = FakeFactory()
    f.manager.vehicles = {car.id: car}
    s = Session(config, f)
    assert await s.call(lambda m: s.vehicle(m, "123456")) is car
    assert await s.call(lambda m: s.vehicle(m, car.id)) is car


async def test_library_error_is_mapped_and_redacted(config):
    s = Session(config, FakeFactory())

    def boom(m):
        raise APIError(f"echo {config.password}")

    with pytest.raises(ToolFailure) as e:
        await s.call(boom)
    assert config.password not in str(e.value)


async def test_concurrent_calls_serialize(config):
    f = FakeFactory()
    f.manager.refresh_delay = 0.05
    s = Session(config, f)
    await asyncio.gather(s.call(lambda m: 1), s.call(lambda m: 2))
    assert f.manager.max_active == 1
    assert f.calls == 1


async def test_send_otp_when_login_needs_it(config):
    f = FakeFactory()
    f.manager.login_result = _otp()
    assert await Session(config, f).send_otp("email") == "Passcode sent by email."
    assert f.manager.sent_otp == OTP_NOTIFY_TYPE.EMAIL
    assert f.manager.refresh_calls == 0


async def test_send_otp_sms_uses_pending_request(config):
    f = FakeFactory()
    f.manager.otp_request = _otp()
    assert await Session(config, f).send_otp("sms") == "Passcode sent by SMS."
    assert f.manager.sent_otp == OTP_NOTIFY_TYPE.SMS
    assert f.manager.login_calls == 0


async def test_send_otp_when_not_needed(config):
    f = FakeFactory()
    msg = await Session(config, f).send_otp("email")
    assert msg == "Already logged in. No passcode needed."
    assert load_token(config).access_token == "logged-in"


async def test_verify_otp_saves_token(config):
    f = FakeFactory()
    f.manager.otp_request = _otp()
    msg = await Session(config, f).verify_otp("123456")
    assert msg == "Logged in. 1 vehicle(s) found."
    assert f.manager.verified_code == "123456"
    assert config.token_path.exists()


async def test_verify_otp_error_is_mapped(config):
    f = FakeFactory()
    f.manager.otp_request = _otp()

    def boom(code):
        raise APIError(f"x {config.pin}")

    f.manager.verify_otp_and_complete_login = boom
    with pytest.raises(ToolFailure) as e:
        await Session(config, f).verify_otp("1")
    assert config.pin not in str(e.value)


async def test_send_otp_failed_login(config):
    f = FakeFactory()
    f.manager.login_result = False
    with pytest.raises(ToolFailure, match="BLUELINK_PASSWORD"):
        await Session(config, f).send_otp("email")
    assert f.manager.sent_otp is None


async def test_keyboard_interrupt_propagates(config):
    def boom(m):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        Session(config, FakeFactory())._run_sync(boom)


async def test_verify_otp_clears_pending_request(config):
    f = FakeFactory()
    f.manager.otp_request = _otp()
    await Session(config, f).verify_otp("123456")
    assert f.manager.otp_request is None


async def test_verify_otp_without_pending_request(config):
    f = FakeFactory()
    with pytest.raises(ToolFailure, match="No passcode is pending. Call send_otp first."):
        await Session(config, f).verify_otp("123456")
    assert f.manager.verified_code is None


async def test_persistence_failure_does_not_replace_result(config, monkeypatch):
    def boom(cfg, token):
        raise OSError("disk full")

    monkeypatch.setattr("bluelink_mcp.session.save_token", boom)
    s = Session(config, FakeFactory(FakeManager(make_token("new"))))
    assert await s.call(lambda m: "ok") == "ok"
