import dataclasses
import os
import stat

import pytest
from hyundai_kia_connect_api.Token import Token

from bluelink_mcp.token_store import load_token, save_token


def test_round_trip_reinjects_secrets_and_never_writes_them(config):
    save_token(config, Token(username="u@x.com", password="pw", pin="1234", access_token="AT"))
    raw = config.token_path.read_text()
    assert "pw" not in raw.replace("password", "") and "1234" not in raw
    t = load_token(config)
    assert (t.access_token, t.password, t.pin) == ("AT", "pw", "1234")


def test_missing_file_returns_none(config):
    assert load_token(config) is None


def test_corrupt_file_returns_none(config):
    config.token_path.parent.mkdir(parents=True)
    config.token_path.write_text("{nope")
    assert load_token(config) is None


@pytest.mark.parametrize("field,value", [("username", "other@x.com"), ("region", 1), ("brand", 1)])
def test_identity_mismatch_returns_none(config, field, value):
    save_token(config, Token(username="u@x.com", password="pw", access_token="AT"))
    assert load_token(dataclasses.replace(config, **{field: value})) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_file_mode_0600(config):
    save_token(config, Token(username="u@x.com", password="pw"))
    assert stat.S_IMODE(config.token_path.stat().st_mode) == 0o600
