from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from hyundai_kia_connect_api import const


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    username: str
    password: str = field(repr=False)
    pin: str | None = field(repr=False)
    region: int
    brand: int
    language: str
    token_path: Path


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable {name}")
    return value


def _lookup(env: Mapping[str, str], name: str, names: Mapping[int, str]) -> int:
    raw = _require(env, name)
    by_name = {v.lower(): k for k, v in names.items()}
    try:
        return by_name[raw.lower()]
    except KeyError:
        valid = ", ".join(names.values())
        raise ConfigError(f"Invalid {name} {raw!r}. Valid values: {valid}") from None


_USA_PIN_BRANDS = {
    k for k, v in const.BRANDS.items() if v in (const.BRAND_HYUNDAI, const.BRAND_GENESIS)
}


def region_name_is_usa(region: int) -> bool:
    return const.REGIONS[region] == const.REGION_USA


def load_config(env: Mapping[str, str]) -> Config:
    username = _require(env, "BLUELINK_USERNAME")
    password = _require(env, "BLUELINK_PASSWORD")
    region = _lookup(env, "BLUELINK_REGION", const.REGIONS)
    brand = _lookup(env, "BLUELINK_BRAND", const.BRANDS)
    pin = env.get("BLUELINK_PIN", "").strip() or None
    if pin is None and region_name_is_usa(region) and brand in _USA_PIN_BRANDS:
        raise ConfigError(
            f"BLUELINK_PIN is required for {const.BRANDS[brand]} in {const.REGIONS[region]}"
        )
    token_override = env.get("BLUELINK_TOKEN_PATH", "").strip()
    token_path = (
        Path(token_override)
        if token_override
        else Path.home() / ".bluelink-mcp" / "token.json"
    )
    return Config(
        username=username,
        password=password,
        pin=pin,
        region=region,
        brand=brand,
        language=env.get("BLUELINK_LANGUAGE", "").strip() or "en",
        token_path=token_path,
    )
