"""Stdio MCP server entry point."""

import logging
import os
import sys
from collections.abc import Mapping

from dotenv import find_dotenv, load_dotenv
from hyundai_kia_connect_api import VehicleManager
from mcp.server.fastmcp import FastMCP

from hyundai_kia_connect_api import const
from hyundai_kia_connect_api.exceptions import APIError

from .config import ConfigError, load_config
from .session import Session
from .tools import register_tools

log = logging.getLogger("bluelink_mcp")


def build_server(env: Mapping[str, str]) -> FastMCP:
    """Build the server from env vars. Makes no network call."""
    config = load_config(env)
    try:
        api = VehicleManager.get_implementation_by_region_brand(
            config.region, config.brand, config.language
        )
    except APIError:
        raise ConfigError(
            f"Region {const.REGIONS[config.region]} with brand "
            f"{const.BRANDS[config.brand]} is not supported by the library."
        ) from None
    server = FastMCP("bluelink")
    names = register_tools(server, Session(config), api)
    log.info("Registered %d tools: %s", len(names), ", ".join(names))
    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    load_dotenv(find_dotenv(usecwd=True), override=False)
    try:
        server = build_server(os.environ)
    except ConfigError as exc:
        print(f"bluelink-mcp: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    server.run("stdio")


if __name__ == "__main__":
    main()
