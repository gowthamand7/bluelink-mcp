import json

import pytest
from hyundai_kia_connect_api import VehicleManager
from hyundai_kia_connect_api.ApiImpl import ApiImpl
from hyundai_kia_connect_api.const import WINDOW_STATE
from hyundai_kia_connect_api.Vehicle import Vehicle
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from bluelink_mcp.session import Session
from bluelink_mcp.tools import confirmation_needed, register_tools, supported_methods
from fakes import FakeCommandManager, FakeFactory

GUARDED = {
    "unlock", "open_charge_port", "start_hazard_lights_and_horn",
    "set_windows", "start_valet_mode", "stop_valet_mode", "open_frunk",
    "door_power_off", "set_v2l_discharge_limit",
}
READ_ONLY = {
    "list_vehicles", "get_vehicle_status", "get_location", "get_trip_info_month",
    "get_trip_info_day", "check_action_status",
}
SENT = {"action_id": "act-1", "message": "Command sent. Use check_action_status to confirm."}


class FakeApi(ApiImpl):
    def lock_action(self, token, vehicle, action):
        return None

    def update_vehicle_with_cached_state(self, token, vehicle):
        return None

    def start_climate(self, token, vehicle, options):
        return None


def _all_api() -> ApiImpl:
    """An ApiImpl that overrides every public method, so every tool registers."""
    names = [m for m in dir(ApiImpl) if not m.startswith("_") and callable(getattr(ApiImpl, m))]
    return type("AllApi", (ApiImpl,), {m: (lambda self, *a, **k: None) for m in names})()


@pytest.fixture
def session(config):
    return Session(config, FakeFactory(FakeCommandManager()))


@pytest.fixture
def fake_session(config):
    manager = FakeCommandManager()
    manager.vehicles = {"v1": Vehicle(id="v1", name="Ioniq")}
    manager.server = FastMCP("t")
    register_tools(manager.server, Session(config, FakeFactory(manager)), _all_api())
    return manager


async def call_tool(server, name, args):
    result = await server.call_tool(name, args)
    if isinstance(result, tuple):
        return result[1]
    text = result[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def test_supported_methods_detects_overrides():
    assert {"lock_action", "start_climate"} <= supported_methods(FakeApi())
    assert "open_frunk" not in supported_methods(FakeApi())


def test_register_filters_by_region(session):
    names = register_tools(FastMCP("t"), session, FakeApi())
    assert {"list_vehicles", "lock", "unlock", "start_climate", "get_vehicle_status"} <= set(names)
    assert "open_frunk" not in names and "send_otp" not in names
    assert names == sorted(names)


def test_hyundai_usa_tool_set(session):
    api = VehicleManager.get_implementation_by_region_brand(3, 2, "en")
    names = set(register_tools(FastMCP("t"), session, api))
    assert {"lock", "unlock", "start_climate", "start_charge", "set_charge_limits",
            "start_hazard_lights_and_horn", "get_trip_info_month"} <= names
    assert not names & {"set_windows", "open_frunk", "start_valet_mode", "open_charge_port", "send_otp"}


def test_confirmation_needed():
    v = Vehicle(id="v1", name="Ioniq")
    assert confirmation_needed(True, v, "unlock the doors") is None
    assert confirmation_needed(False, v, "unlock the doors") == (
        "This will unlock the doors on Ioniq. Nothing was sent. "
        "Call again with confirm=true to proceed."
    )
    assert "on v2." in confirmation_needed(False, Vehicle(id="v2"), "x")


async def test_unlock_without_confirm_sends_nothing(fake_session):
    result = await call_tool(fake_session.server, "unlock", {"vehicle_id": "v1"})
    assert "Nothing was sent" in result and "Ioniq" in result
    assert fake_session.unlock_calls == 0


async def test_unlock_with_confirm_returns_action_id(fake_session):
    result = await call_tool(fake_session.server, "unlock", {"vehicle_id": "v1", "confirm": True})
    assert result == SENT
    assert fake_session.unlock_calls == 1


@pytest.mark.parametrize(
    "tool,args,expected",
    [
        ("lock", {}, ("lock", "LIB-ID-KMHXX00XXXX123456")),
        ("get_vehicle_status", {}, ("cached", "LIB-ID-KMHXX00XXXX123456")),
        ("get_location", {}, ("cached", "LIB-ID-KMHXX00XXXX123456")),
    ],
)
async def test_short_vin_id_reaches_library_as_library_id(fake_session, tool, args, expected):
    car = Vehicle(id="LIB-ID-KMHXX00XXXX123456", name="2022 TESTCAR", VIN="KMHXX00XXXX123456")
    fake_session.vehicles = {car.id: car}
    await call_tool(fake_session.server, tool, {"vehicle_id": "123456", **args})
    assert fake_session.commands[0] == expected


async def test_unknown_vehicle_fails(fake_session):
    with pytest.raises(ToolError, match="Unknown vehicle_id"):
        await call_tool(fake_session.server, "lock", {"vehicle_id": "nope"})


async def test_set_windows_close_needs_no_confirm(fake_session):
    result = await call_tool(fake_session.server, "set_windows",
                             {"vehicle_id": "v1", "front_left": "closed"})
    assert result == SENT
    (_, _, opts) = fake_session.commands[0]
    assert opts.front_left == WINDOW_STATE.CLOSED and opts.back_right is None


async def test_set_windows_open_needs_confirm(fake_session):
    result = await call_tool(fake_session.server, "set_windows",
                             {"vehicle_id": "v1", "back_left": "vent"})
    assert "open windows" in result and "Nothing was sent" in result
    assert fake_session.commands == []


async def test_start_climate_maps_options(fake_session):
    await call_tool(fake_session.server, "start_climate", {
        "vehicle_id": "v1", "temperature": 72, "heating": True,
    })
    (_, _, opts) = fake_session.commands[0]
    assert (opts.set_temp, opts.duration, opts.climate, opts.heating, opts.defrost) == (
        72, 10, True, 1, False)
    assert opts.temp_unit is None


async def test_get_vehicle_status_refresh(fake_session):
    await call_tool(fake_session.server, "get_vehicle_status", {"vehicle_id": "v1"})
    await call_tool(fake_session.server, "get_vehicle_status", {"vehicle_id": "v1", "refresh": True})
    assert [c[0] for c in fake_session.commands] == ["cached", "force"]


async def test_check_action_status_wait(fake_session):
    result = await call_tool(fake_session.server, "check_action_status",
                             {"vehicle_id": "v1", "action_id": "a", "wait": True})
    assert result == {"action_id": "a", "status": "SUCCESS"}
    assert fake_session.commands[0] == ("check", "v1", "a", True, 60)


async def test_list_vehicles(fake_session):
    result = await call_tool(fake_session.server, "list_vehicles", {})
    assert result["vehicles"][0]["name"] == "Ioniq"


async def test_guarded_tools_have_destructive_hint(fake_session):
    tools = {t.name: t for t in await fake_session.server.list_tools()}
    assert GUARDED <= set(tools)
    for name, tool in tools.items():
        assert tool.annotations.destructiveHint is (name in GUARDED), name
        assert tool.annotations.readOnlyHint is (name in READ_ONLY), name
        if name in GUARDED:
            assert "confirm" in tool.inputSchema["properties"], name
            assert "confirm" in tool.description, name


async def test_set_charge_limits_rejects_out_of_range(fake_session):
    with pytest.raises(ToolError, match="50"):
        await call_tool(fake_session.server, "set_charge_limits",
                        {"vehicle_id": "v1", "ac_percent": 45, "dc_percent": 80})
    with pytest.raises(ToolError, match="10"):
        await call_tool(fake_session.server, "set_charge_limits",
                        {"vehicle_id": "v1", "ac_percent": 85, "dc_percent": 80})
    assert fake_session.commands == []


async def test_set_charge_limits_sends(fake_session):
    result = await call_tool(fake_session.server, "set_charge_limits",
                             {"vehicle_id": "v1", "ac_percent": 90, "dc_percent": 80})
    assert result == SENT
    assert fake_session.commands == [("set_charge_limits", "v1", 90, 80)]


async def test_schedule_parses_times_and_rejects_bad_keys(fake_session):
    await call_tool(fake_session.server, "schedule_charging_and_climate", {
        "vehicle_id": "v1",
        "options": {"off_peak_start_time": "22:30",
                    "first_departure": {"enabled": True, "days": [1, 2], "time": "07:15"}},
    })
    (_, _, opts) = fake_session.commands[0]
    assert (opts.off_peak_start_time.hour, opts.off_peak_start_time.minute) == (22, 30)
    assert opts.first_departure.time.hour == 7 and opts.first_departure.days == [1, 2]
    with pytest.raises(ToolError, match="bogus"):
        await call_tool(fake_session.server, "schedule_charging_and_climate",
                        {"vehicle_id": "v1", "options": {"bogus": 1}})


async def test_set_navigation_builds_pois(fake_session):
    await call_tool(fake_session.server, "set_navigation", {
        "vehicle_id": "v1",
        "destinations": [{"name": "A", "latitude": 1.5, "longitude": 2.5},
                         {"name": "B", "latitude": 3.0, "longitude": 4.0, "address": "1 Main"}],
    })
    (_, _, pois) = fake_session.commands[0]
    assert [(p.name, p.waypoint_id, p.addr, p.coord.lat, p.coord.lon) for p in pois] == [
        ("A", 1, "", 1.5, 2.5), ("B", 2, "1 Main", 3.0, 4.0)]


NO_ACTION = (
    "No action ID was returned. The command may not apply to this vehicle "
    "(for example, charging commands need an EV in some regions)."
)

GUARDED_ARGS = {
    "set_v2l_discharge_limit": {"limit_percent": 20},
    "set_windows": {"front_left": "open"},
}


@pytest.mark.parametrize("name", sorted(GUARDED))
async def test_guarded_tool_without_confirm_sends_nothing(fake_session, name):
    args = {"vehicle_id": "v1", **GUARDED_ARGS.get(name, {})}
    result = await call_tool(fake_session.server, name, args)
    assert "Nothing was sent" in result
    assert fake_session.commands == []


async def test_set_windows_mixed_without_confirm_sends_nothing(fake_session):
    result = await call_tool(fake_session.server, "set_windows", {
        "vehicle_id": "v1", "front_left": "closed", "front_right": "open"})
    assert "Nothing was sent" in result
    assert fake_session.commands == []


async def test_none_action_id_is_not_reported_as_sent(fake_session):
    fake_session.return_none = True
    result = await call_tool(fake_session.server, "start_charge", {"vehicle_id": "v1"})
    assert result == {"action_id": None, "message": NO_ACTION}


async def test_start_climate_whole_temperature_is_int(fake_session):
    await call_tool(fake_session.server, "start_climate", {
        "vehicle_id": "v1", "temperature": 72.0})
    (_, _, opts) = fake_session.commands[0]
    assert opts.set_temp == 72 and isinstance(opts.set_temp, int)
    await call_tool(fake_session.server, "start_climate", {
        "vehicle_id": "v1", "temperature": 21.5})
    assert fake_session.commands[1][2].set_temp == 21.5


async def test_start_climate_sends_without_confirm(fake_session):
    result = await call_tool(fake_session.server, "start_climate", {"vehicle_id": "v1", "temperature": 70})
    assert result == SENT
    assert fake_session.commands[0][0] == "start_climate"
