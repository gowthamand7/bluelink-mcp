"""MCP tool table, region capability filter and confirm guard."""

import dataclasses
import datetime as dt
import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from hyundai_kia_connect_api import VehicleManager
from hyundai_kia_connect_api.ApiImpl import (
    ApiImpl,
    ClimateRequestOptions,
    POICoord,
    POIInfo,
    ScheduleChargingClimateRequestOptions,
    WindowRequestOptions,
)
from hyundai_kia_connect_api.const import WINDOW_STATE
from hyundai_kia_connect_api.Vehicle import Vehicle
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from .errors import ToolFailure
from .serialize import to_jsonable, vehicle_location, vehicle_status, vehicle_summary
from .session import Session

SENT_MESSAGE = "Command sent. Use check_action_status to confirm."
CONFIRM_RULE = (
    "Requires confirm=true. Without it, nothing is sent and the tool explains the effect."
)

WindowState = Literal["closed", "open", "vent"]
_WINDOW_STATES = {
    "closed": WINDOW_STATE.CLOSED,
    "open": WINDOW_STATE.OPEN,
    "vent": WINDOW_STATE.VENTILATION,
}

ScheduleOptions = ScheduleChargingClimateRequestOptions
DepartureOptions = ScheduleChargingClimateRequestOptions.DepartureOptions
_TIME_FIELDS = {"time", "off_peak_start_time", "off_peak_end_time"}
_DEPARTURE_FIELDS = {"first_departure", "second_departure"}


@dataclasses.dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable[..., Awaitable[Any]]
    requires: tuple[str, ...]
    read_only: bool = False
    destructive: bool = False


class Destination(BaseModel):
    name: str
    latitude: float
    longitude: float
    address: str = ""


def confirmation_needed(confirm: bool, vehicle: Vehicle, effect: str) -> str | None:
    if confirm:
        return None
    return (
        f"This will {effect} on {vehicle.name or vehicle.id}. Nothing was sent. "
        "Call again with confirm=true to proceed."
    )


def supported_methods(api: ApiImpl) -> set[str]:
    """ApiImpl methods that the region's implementation overrides."""
    return {
        m
        for m in dir(type(api))
        if not m.startswith("_") and getattr(type(api), m, None) is not getattr(ApiImpl, m, None)
    }


NO_ACTION_MESSAGE = (
    "No action ID was returned. The command may not apply to this vehicle "
    "(for example, charging commands need an EV in some regions)."
)


def _sent(action_id: str | None) -> dict[str, Any]:
    if action_id is None:
        return {"action_id": None, "message": NO_ACTION_MESSAGE}
    return {"action_id": action_id, "message": SENT_MESSAGE}


def _parse_time(value: Any, key: str) -> dt.time:
    try:
        return dt.datetime.strptime(str(value), "%H:%M").time()
    except ValueError:
        raise ToolFailure(f"Option '{key}' must be a time as HH:MM, got '{value}'.") from None


def _build(cls: type, options: dict[str, Any], where: str) -> Any:
    valid = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(set(options) - valid)
    if unknown:
        raise ToolFailure(
            f"Unknown {where} option(s): {', '.join(unknown)}. "
            f"Valid options: {', '.join(sorted(valid))}."
        )
    values = dict(options)
    for key, value in options.items():
        if value is None:
            continue
        if key in _TIME_FIELDS:
            values[key] = _parse_time(value, key)
        elif key in _DEPARTURE_FIELDS:
            if not isinstance(value, dict):
                raise ToolFailure(f"Option '{key}' must be an object.")
            values[key] = _build(DepartureOptions, value, key)
    return cls(**values)


def build_tools(session: Session) -> list[ToolSpec]:
    async def command(
        vehicle_id: str,
        send: Callable[[VehicleManager, str], str | None],
        effect: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any] | str:
        """Send a command; when `effect` is set, require confirm first."""

        def work(m: VehicleManager) -> dict[str, Any] | str:
            vehicle = session.vehicle(m, vehicle_id)
            if effect is not None:
                message = confirmation_needed(confirm, vehicle, effect)
                if message is not None:
                    return message
            return _sent(send(m, vehicle.id))

        return await session.call(work)

    def simple(name: str, requires: str, doc: str) -> ToolSpec:
        """A command tool that takes only vehicle_id and calls manager.<name>."""

        async def fn(vehicle_id: str):
            return await command(vehicle_id, lambda m, vid: getattr(m, name)(vid))

        fn.__doc__ = doc
        return ToolSpec(name, fn, (requires,))

    def guarded(name: str, requires: str, effect: str, doc: str) -> ToolSpec:
        """A guarded command tool that takes vehicle_id and confirm."""

        async def fn(vehicle_id: str, confirm: bool = False):
            return await command(
                vehicle_id, lambda m, vid: getattr(m, name)(vid), effect, confirm
            )

        fn.__doc__ = f"{doc} {CONFIRM_RULE}"
        return ToolSpec(name, fn, (requires,), destructive=True)

    def schedule(name: str, doc: str) -> ToolSpec:
        async def fn(vehicle_id: str, options: dict[str, Any]):
            opts = _build(ScheduleOptions, options, "schedule")
            return await command(vehicle_id, lambda m, vid: getattr(m, name)(vid, opts))

        fn.__doc__ = (
            f"{doc} `options` holds ScheduleChargingClimateRequestOptions fields: "
            "first_departure / second_departure ({enabled, days (Sun=0..Sat=6), "
            "time 'HH:MM', climate_enabled, temperature, defrost}), charging_enabled, "
            "off_peak_start_time / off_peak_end_time ('HH:MM'), "
            "off_peak_charge_only_enabled, climate_enabled, temperature (°F in the USA, "
            "°C elsewhere), defrost. Omitted fields stay unchanged."
        )
        return ToolSpec(name, fn, (name,))

    # ---- read-only tools ----

    async def list_vehicles():
        """List the vehicles on the account with their vehicle_id, name, model and year."""
        return await session.call(
            lambda m: {"vehicles": [vehicle_summary(v) for v in m.vehicles.values()]}
        )

    async def get_vehicle_status(vehicle_id: str, refresh: bool = False):
        """Get the vehicle status (battery, doors, climate, range, and more).
        refresh=false returns the cloud's cached state. refresh=true wakes the car
        for live data; it is slower and drains the 12V battery, so use it sparingly."""

        def work(m: VehicleManager) -> dict[str, Any]:
            vehicle = session.vehicle(m, vehicle_id)
            if refresh:
                m.force_refresh_vehicle_state(vehicle.id)
            else:
                m.update_vehicle_with_cached_state(vehicle.id)
            return vehicle_status(vehicle)

        return await session.call(work)

    async def get_location(vehicle_id: str):
        """Get the vehicle's last known location: latitude, longitude and update time.
        The address is included only when the library provides one."""

        def work(m: VehicleManager) -> dict[str, Any]:
            vehicle = session.vehicle(m, vehicle_id)
            m.update_vehicle_with_cached_state(vehicle.id)
            return vehicle_location(vehicle)

        return await session.call(work)

    async def get_trip_info_month(vehicle_id: str, yyyymm: str):
        """Get trip statistics for one month. yyyymm is the month, e.g. "202611"."""
        if not re.fullmatch(r"\d{6}", yyyymm):
            raise ToolFailure("yyyymm must be 6 digits, e.g. 202611.")

        def work(m: VehicleManager) -> Any:
            vehicle = session.vehicle(m, vehicle_id)
            m.update_month_trip_info(vehicle.id, yyyymm)
            return to_jsonable(vehicle.month_trip_info)

        return await session.call(work)

    async def get_trip_info_day(vehicle_id: str, yyyymmdd: str):
        """Get the trips for one day. yyyymmdd is the date, e.g. "20261117"."""
        if not re.fullmatch(r"\d{8}", yyyymmdd):
            raise ToolFailure("yyyymmdd must be 8 digits, e.g. 20261117.")

        def work(m: VehicleManager) -> Any:
            vehicle = session.vehicle(m, vehicle_id)
            m.update_day_trip_info(vehicle.id, yyyymmdd)
            return to_jsonable(vehicle.day_trip_info)

        return await session.call(work)

    async def check_action_status(vehicle_id: str, action_id: str, wait: bool = False):
        """Check the result of a command by its action_id: PENDING, SUCCESS, FAILED
        or TIMEOUT. wait=true waits up to 60 seconds for a final result."""

        def work(m: VehicleManager) -> dict[str, Any]:
            vehicle = session.vehicle(m, vehicle_id)
            if wait:
                status = m.check_action_status(vehicle.id, action_id, synchronous=True, timeout=60)
            else:
                status = m.check_action_status(vehicle.id, action_id, synchronous=False)
            return {"action_id": action_id, "status": to_jsonable(status)}

        return await session.call(work)

    # ---- commands with arguments ----

    async def start_climate(
        vehicle_id: str,
        temperature: float,
        duration_min: int = 10,
        defrost: bool = False,
        heating: bool = False,
        front_left_seat: int | None = None,
        front_right_seat: int | None = None,
        steering_wheel: int | None = None,
    ):
        """Start climate control. temperature is in °F in the USA, °C elsewhere.
        duration_min is minutes. heating turns on the heating accessories
        (for example the rear window defroster) where the vehicle supports them.
        Seat and steering wheel values are the region's level codes; omit to leave off.
        On gas vehicles this starts the engine."""
        opts = ClimateRequestOptions(
            set_temp=int(temperature) if float(temperature).is_integer() else temperature,
            duration=duration_min,
            defrost=defrost,
            climate=True,
            heating=1 if heating else 0,
            front_left_seat=front_left_seat,
            front_right_seat=front_right_seat,
            steering_wheel=steering_wheel,
        )
        return await command(vehicle_id, lambda m, vid: m.start_climate(vid, opts))

    async def set_charge_limits(vehicle_id: str, ac_percent: int, dc_percent: int):
        """Set the maximum charge level in percent for AC (slow) and DC (fast)
        charging. Each value must be 50 to 100 in steps of 10."""
        for value in (ac_percent, dc_percent):
            if not 50 <= value <= 100 or value % 10:
                raise ToolFailure(
                    "ac_percent and dc_percent must be 50 to 100 in steps of 10."
                )
        return await command(
            vehicle_id, lambda m, vid: m.set_charge_limits(vid, ac_percent, dc_percent)
        )

    async def set_charging_current(vehicle_id: str, level: int):
        """Set the AC charging current level: 1 = 100%, 2 = 90%, 3 = 60%."""
        if level not in (1, 2, 3):
            raise ToolFailure("level must be 1, 2 or 3.")
        return await command(vehicle_id, lambda m, vid: m.set_charging_current(vid, level))

    async def set_windows(
        vehicle_id: str,
        front_left: WindowState | None = None,
        front_right: WindowState | None = None,
        back_left: WindowState | None = None,
        back_right: WindowState | None = None,
        confirm: bool = False,
    ):
        """Open, vent or close windows. Omitted windows stay unchanged.
        Closing needs no confirm. Requires confirm=true when any window is "open"
        or "vent"; without it, nothing is sent and the tool explains the effect."""
        states = (front_left, front_right, back_left, back_right)
        if all(s is None for s in states):
            raise ToolFailure("Give at least one window state.")
        opts = WindowRequestOptions(
            front_left=_WINDOW_STATES.get(front_left),
            front_right=_WINDOW_STATES.get(front_right),
            back_left=_WINDOW_STATES.get(back_left),
            back_right=_WINDOW_STATES.get(back_right),
        )
        opening = any(s in ("open", "vent") for s in states)
        return await command(
            vehicle_id,
            lambda m, vid: m.set_windows_state(vid, opts),
            "open windows" if opening else None,
            confirm,
        )

    async def set_charge_alarm(
        vehicle_id: str,
        before_10min: bool = False,
        before_20min: bool = False,
        before_30min: bool = False,
    ):
        """Set charge-complete alarms 10, 20 and/or 30 minutes before charging ends."""
        return await command(
            vehicle_id,
            lambda m, vid: m.set_charge_alarm(vid, before_10min, before_20min, before_30min),
        )

    async def set_v2l_discharge_limit(vehicle_id: str, limit_percent: int, confirm: bool = False):
        """Set the vehicle-to-load (V2L) discharge limit: the battery percent at
        which V2L power output stops."""
        return await command(
            vehicle_id,
            lambda m, vid: m.set_vehicle_to_load_discharge_limit(vid, limit_percent),
            "change the vehicle-to-load discharge limit",
            confirm,
        )

    set_v2l_discharge_limit.__doc__ = f"{set_v2l_discharge_limit.__doc__} {CONFIRM_RULE}"

    async def set_navigation(vehicle_id: str, destinations: list[Destination]):
        """Send one or more destinations to the car's navigation, in route order.
        Each has name, latitude, longitude and an optional address."""
        if not destinations:
            raise ToolFailure("Give at least one destination.")
        pois = [
            POIInfo(
                name=d.name,
                addr=d.address,
                coord=POICoord(lat=d.latitude, lon=d.longitude),
                waypoint_id=i,
            )
            for i, d in enumerate(destinations, start=1)
        ]
        return await command(vehicle_id, lambda m, vid: m.set_navigation(vid, pois))

    # ---- login ----

    async def send_otp(method: Literal["email", "sms"]):
        """Send a one-time login passcode by email or SMS. Use when a tool says
        login needs a passcode; then call verify_otp with the code."""
        return await session.send_otp(method)

    async def verify_otp(code: str):
        """Complete login with the one-time passcode from send_otp."""
        return await session.verify_otp(code)

    return [
        ToolSpec("list_vehicles", list_vehicles, (), read_only=True),
        ToolSpec("get_vehicle_status", get_vehicle_status,
                 ("update_vehicle_with_cached_state",), read_only=True),
        ToolSpec("get_location", get_location,
                 ("update_vehicle_with_cached_state",), read_only=True),
        ToolSpec("get_trip_info_month", get_trip_info_month,
                 ("update_month_trip_info",), read_only=True),
        ToolSpec("get_trip_info_day", get_trip_info_day,
                 ("update_day_trip_info",), read_only=True),
        ToolSpec("check_action_status", check_action_status,
                 ("check_action_status",), read_only=True),
        simple("lock", "lock_action", "Lock the doors."),
        guarded("unlock", "lock_action", "unlock the doors", "Unlock the doors."),
        ToolSpec("start_climate", start_climate, ("start_climate",)),
        simple("stop_climate", "stop_climate", "Stop climate control."),
        simple("start_charge", "start_charge", "Start charging (EV/PHEV, plugged in)."),
        simple("stop_charge", "stop_charge", "Stop charging."),
        ToolSpec("set_charge_limits", set_charge_limits, ("set_charge_limits",)),
        ToolSpec("set_charging_current", set_charging_current, ("set_charging_current",)),
        guarded("open_charge_port", "charge_port_action", "open the charge port",
                "Open the charge port door."),
        simple("close_charge_port", "charge_port_action", "Close the charge port door."),
        simple("start_hazard_lights", "start_hazard_lights", "Flash the hazard lights."),
        guarded("start_hazard_lights_and_horn", "start_hazard_lights_and_horn",
                "flash the hazard lights and sound the horn",
                "Flash the hazard lights and sound the horn."),
        ToolSpec("set_windows", set_windows, ("set_windows_state",), destructive=True),
        simple("start_pet_care", "start_pet_care", "Turn on pet care mode."),
        simple("stop_pet_care", "stop_pet_care", "Turn off pet care mode."),
        simple("start_battery_conditioning", "start_battery_conditioning",
               "Start battery conditioning (pre-heat or cool the high-voltage battery)."),
        simple("stop_battery_conditioning", "stop_battery_conditioning",
               "Stop battery conditioning."),
        guarded("start_valet_mode", "valet_mode_action", "turn on valet mode",
                "Turn on valet mode."),
        guarded("stop_valet_mode", "valet_mode_action", "turn off valet mode",
                "Turn off valet mode."),
        guarded("open_frunk", "open_frunk", "open the front trunk", "Open the front trunk."),
        guarded("door_power_off", "door_power_off", "cut power to the doors",
                "Cut power to the doors."),
        simple("turn_off_lamp", "turn_off_lamp", "Turn off the lamps."),
        simple("stop_rear_seat_alarm", "stop_rear_seat_alarm", "Stop the rear seat alarm."),
        ToolSpec("set_charge_alarm", set_charge_alarm, ("set_charge_alarm",)),
        ToolSpec("set_v2l_discharge_limit", set_v2l_discharge_limit,
                 ("set_vehicle_to_load_discharge_limit",), destructive=True),
        schedule("schedule_charging_and_climate",
                 "Set scheduled charging and departure climate."),
        schedule("schedule_reservation_charge", "Set the scheduled (reserved) charging."),
        schedule("schedule_reservation_hvac", "Set the scheduled (reserved) climate."),
        schedule("schedule_reservation_engine", "Set the scheduled (reserved) engine start."),
        ToolSpec("set_navigation", set_navigation, ("set_navigation",)),
        ToolSpec("send_otp", send_otp, ("send_otp",)),
        ToolSpec("verify_otp", verify_otp, ("verify_otp_and_complete_login",)),
    ]


def register_tools(server: FastMCP, session: Session, api: ApiImpl) -> list[str]:
    """Register the tools whose required ApiImpl methods this region implements."""
    supported = supported_methods(api)
    names = []
    for spec in build_tools(session):
        if not set(spec.requires) <= supported:
            continue
        server.add_tool(
            spec.fn,
            name=spec.name,
            description=inspect.cleandoc(spec.fn.__doc__ or ""),
            annotations=ToolAnnotations(
                readOnlyHint=spec.read_only, destructiveHint=spec.destructive
            ),
        )
        names.append(spec.name)
    return sorted(names)
