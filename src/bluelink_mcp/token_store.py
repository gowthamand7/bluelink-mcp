from __future__ import annotations

import getpass
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from hyundai_kia_connect_api.Token import Token

from .config import Config

log = logging.getLogger("bluelink_mcp")


def _restrict_windows_acl(path: Path) -> None:
    user = os.environ.get("USERNAME") or getpass.getuser()
    try:
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            check=False,
            capture_output=True,
        )
        failed = result.returncode != 0
    except OSError:
        failed = True
    if failed:
        log.warning("Could not restrict permissions on %s", path)


def save_token(config: Config, token: Token) -> None:
    data = token.to_dict()
    data["password"] = ""
    data["pin"] = None
    payload = {
        "username": config.username,
        "region": config.region,
        "brand": config.brand,
        "token": data,
    }
    path = config.token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".token-", suffix=".tmp")
    try:
        # mkstemp creates the file with mode 0600 on POSIX.
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        if os.name == "nt":
            _restrict_windows_acl(Path(tmp))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_token(config: Config) -> Token | None:
    try:
        payload = json.loads(config.token_path.read_text(encoding="utf-8"))
        if (
            payload["username"] != config.username
            or payload["region"] != config.region
            or payload["brand"] != config.brand
        ):
            return None
        data = dict(payload["token"])
        data["password"] = config.password
        data["pin"] = config.pin
        return Token.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
