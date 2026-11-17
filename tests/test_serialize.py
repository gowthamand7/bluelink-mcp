import datetime
import enum
import json

from hyundai_kia_connect_api.Vehicle import TripInfo, Vehicle

from bluelink_mcp.serialize import (
    public_vehicle_id,
    to_jsonable,
    vehicle_location,
    vehicle_status,
    vehicle_summary,
)


def make_vehicle():
    v = Vehicle(id="v1", name="Ioniq", model="IONIQ 5", year=2024, VIN="KM8ABCDEF123456", key="secretkey")
    v.car_battery_percentage = 80
    return v


def test_status_hides_vin_and_key_and_raw_data():
    s = vehicle_status(make_vehicle())
    assert s["id"] == "123456" and "VIN" not in s and "key" not in s and "data" not in s
    assert "vin_last6" not in s
    assert s["car_battery_percentage"] == 80
    json.dumps(s)  # must not raise


def test_status_excludes_trip_and_supports_fields():
    s = vehicle_status(make_vehicle())
    for k in ("supports", "month_trip_info", "day_trip_info", "daily_stats"):
        assert k not in s
    assert not any(k.startswith(("_", "supports_")) for k in s)


def test_status_includes_properties_and_serializes_datetimes():
    v = make_vehicle()
    v.odometer = (1234.5, 1)
    v.last_updated_at = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    s = vehicle_status(v)
    assert s["odometer"] == 1234.5
    assert datetime.datetime.fromisoformat(s["last_updated_at"]) == datetime.datetime(
        2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
    )
    json.dumps(s)


def test_summary():
    assert vehicle_summary(make_vehicle()) == {"id": "123456", "name": "Ioniq", "model": "IONIQ 5", "year": 2024}


def test_id_never_contains_full_vin_even_when_library_id_does():
    v = Vehicle(id="H0000000000KMHXX00XXXX123456", name="2022 TESTCAR", VIN="KMHXX00XXXX123456")
    blob = json.dumps([vehicle_summary(v), vehicle_status(v)])
    assert "KMHXX00XXXX123456" not in blob
    assert vehicle_summary(v)["id"] == "123456"


def test_id_falls_back_to_library_id_without_vin():
    assert public_vehicle_id(Vehicle(id="v9")) == "v9"


def test_year_parsed_from_name_when_missing():
    v = Vehicle(id="x", name="2022 TESTCAR", VIN="KMHXX00XXXX123456")
    assert vehicle_summary(v)["year"] == 2022
    assert vehicle_status(v)["year"] == 2022
    assert vehicle_summary(Vehicle(id="y", name="TESTCAR"))["year"] is None


def test_status_drops_unordered_location_and_geocode_tuples():
    v = make_vehicle()
    v.location = (40.12, -75.34, datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc))
    s = vehicle_status(v)
    assert "location" not in s and "geocode" not in s
    assert s["location_latitude"] == 40.12 and s["location_longitude"] == -75.34


def test_location():
    v = make_vehicle()
    v.location = (37.5, 127.0, datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc))
    v.geocode = ("Home", "1 Main St")
    loc = vehicle_location(v)
    assert loc["latitude"] == 37.5 and loc["longitude"] == 127.0
    assert datetime.datetime.fromisoformat(loc["updated_at"]) == datetime.datetime(
        2026, 1, 2, tzinfo=datetime.timezone.utc
    )
    assert loc["address"] == "1 Main St" and loc["place_name"] == "Home"
    json.dumps(loc)


def test_location_without_data():
    loc = vehicle_location(make_vehicle())
    assert loc["latitude"] is None
    assert "address" not in loc and "place_name" not in loc


def test_to_jsonable_drops_none_and_private():
    assert to_jsonable(TripInfo(distance=12.5)) == {"distance": 12.5}


def test_to_jsonable_scalars_and_containers():
    class Color(enum.Enum):
        RED = 1

    assert to_jsonable(Color.RED) == "RED"
    assert to_jsonable(datetime.date(2026, 1, 2)) == "2026-01-02"
    assert to_jsonable(datetime.time(1, 2, 3)) == "01:02:03"
    assert to_jsonable(datetime.timezone.utc) == "UTC"
    assert to_jsonable({"a": [Color.RED, (1, 2)]}) == {"a": ["RED", [1, 2]]}
