from pathlib import Path

import pytest

from bluelink_mcp.config import ConfigError, load_config

BASE = {"BLUELINK_USERNAME": "u@x.com", "BLUELINK_PASSWORD": "pw",
        "BLUELINK_PIN": "1234", "BLUELINK_REGION": "usa", "BLUELINK_BRAND": "hyundai"}


def test_parses_region_and_brand_case_insensitive():
    c = load_config(BASE)
    assert (c.region, c.brand, c.language) == (3, 2, "en")
    assert c.token_path == Path.home() / ".bluelink-mcp" / "token.json"


def test_token_path_override(tmp_path):
    c = load_config({**BASE, "BLUELINK_TOKEN_PATH": str(tmp_path / "t.json")})
    assert c.token_path == tmp_path / "t.json"


@pytest.mark.parametrize("missing", ["BLUELINK_USERNAME", "BLUELINK_PASSWORD", "BLUELINK_REGION", "BLUELINK_BRAND"])
def test_missing_required(missing):
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_config(env)


def test_unknown_region_lists_valid_names():
    with pytest.raises(ConfigError, match="USA"):
        load_config({**BASE, "BLUELINK_REGION": "Mars"})


def test_pin_required_for_hyundai_usa():
    env = {k: v for k, v in BASE.items() if k != "BLUELINK_PIN"}
    with pytest.raises(ConfigError, match="BLUELINK_PIN"):
        load_config(env)


def test_pin_optional_elsewhere():
    env = {k: v for k, v in BASE.items() if k != "BLUELINK_PIN"}
    assert load_config({**env, "BLUELINK_REGION": "Europe"}).pin is None


def test_repr_hides_secrets():
    r = repr(load_config(BASE))
    assert "pw" not in r and "1234" not in r


def test_pin_required_for_genesis_usa():
    env = {k: v for k, v in BASE.items() if k != "BLUELINK_PIN"}
    with pytest.raises(ConfigError, match="BLUELINK_PIN"):
        load_config({**env, "BLUELINK_BRAND": "Genesis"})
