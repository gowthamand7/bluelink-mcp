import pytest

from bluelink_mcp.config import Config


@pytest.fixture
def config(tmp_path):
    return Config(
        username="u@x.com",
        password="pw",
        pin="1234",
        region=3,
        brand=2,
        language="en",
        token_path=tmp_path / "sub" / "token.json",
    )
