import asyncio
import os

import pytest

from bluelink_mcp.server import build_server, main

BASE = {
    "BLUELINK_USERNAME": "u@example.com",
    "BLUELINK_PASSWORD": "pw",
    "BLUELINK_PIN": "1234",
    "BLUELINK_REGION": "USA",
    "BLUELINK_BRAND": "Hyundai",
}


def test_build_server_registers_hyundai_usa_tools(tmp_path):
    s = build_server({**BASE, "BLUELINK_TOKEN_PATH": str(tmp_path / "t.json")})
    names = {t.name for t in asyncio.run(s.list_tools())}
    assert "unlock" in names and "open_frunk" not in names


def test_main_exits_2_on_bad_config(monkeypatch, capsys):
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr("bluelink_mcp.server.load_dotenv", lambda *a, **kw: False)
    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 2 and "BLUELINK_USERNAME" in capsys.readouterr().err


def test_unsupported_region_brand_is_config_error(tmp_path):
    from bluelink_mcp.config import ConfigError

    env = {**BASE, "BLUELINK_REGION": "Brazil", "BLUELINK_BRAND": "Kia",
           "BLUELINK_TOKEN_PATH": str(tmp_path / "t.json")}
    with pytest.raises(ConfigError, match="Region Brazil with brand Kia is not supported"):
        build_server(env)
