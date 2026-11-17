"""JSON-safe serialization of hyundai_kia_connect_api objects."""

import dataclasses
import datetime
import enum
import inspect
import re
from typing import Any

from hyundai_kia_connect_api import Vehicle

_STATUS_EXCLUDED = frozenset(
    {
        "data", "key", "VIN", "supports", "month_trip_info", "day_trip_info", "daily_stats",
        # Tuples with an inconsistent element order; the named lat/lon fields are kept.
        "location", "geocode",
    }
)
_YEAR_IN_NAME = re.compile(r"\b(?:19|20)\d{2}\b")


_LOCATION_KEYS = frozenset({"latitude", "longitude", "updated_at"})


def to_jsonable(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, datetime.tzinfo):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {}
        for f in dataclasses.fields(value):
            if f.name.startswith("_"):
                continue
            item = getattr(value, f.name)
            if item is not None:
                out[f.name] = to_jsonable(item)
        return out
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    return value


def public_vehicle_id(v: Vehicle) -> str:
    """Short ID shown to clients: the VIN's last 6 characters, else the library ID.

    Some regions (Hyundai USA) embed the full VIN in the library ID, so it is never shown.
    """
    return v.VIN[-6:] if v.VIN else v.id


def _year(v: Vehicle) -> int | None:
    if v.year is not None:
        return v.year
    match = _YEAR_IN_NAME.search(v.name or "")
    return int(match.group(0)) if match else None


def vehicle_summary(v: Vehicle) -> dict:
    return {
        "id": public_vehicle_id(v),
        "name": v.name,
        "model": v.model,
        "year": _year(v),
    }


def vehicle_status(v: Vehicle) -> dict:
    out: dict[str, Any] = {}
    for f in dataclasses.fields(v):
        if f.name.startswith("_") or f.name in _STATUS_EXCLUDED:
            continue
        out[f.name] = getattr(v, f.name)
    for name, _ in inspect.getmembers(type(v), lambda o: isinstance(o, property)):
        # supports_* are deprecated aliases of Vehicle.supports; skip them.
        if name.startswith(("_", "supports_")) or name in _STATUS_EXCLUDED:
            continue
        try:
            out[name] = getattr(v, name)
        except Exception:
            continue
    out["id"] = public_vehicle_id(v)
    out["year"] = _year(v)
    return {k: to_jsonable(val) for k, val in out.items() if val is not None}


def vehicle_location(v: Vehicle) -> dict:
    try:
        place_name, address = v.geocode
    except Exception:
        place_name = address = None
    out = {
        "latitude": v.location_latitude,
        "longitude": v.location_longitude,
        "updated_at": to_jsonable(v.location_last_updated_at),
        "address": address,
        "place_name": place_name,
    }
    return {k: val for k, val in out.items() if val is not None or k in _LOCATION_KEYS}
