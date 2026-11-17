from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from hyundai_kia_connect_api import VehicleManager
from hyundai_kia_connect_api.const import OTP_NOTIFY_TYPE
from hyundai_kia_connect_api.Token import Token
from hyundai_kia_connect_api.Vehicle import Vehicle

from .config import Config
from .errors import ToolFailure, to_tool_failure
from .serialize import public_vehicle_id
from .token_store import load_token, save_token

log = logging.getLogger("bluelink_mcp")

T = TypeVar("T")
ManagerFactory = Callable[[Config, Token | None], VehicleManager]


def default_manager_factory(config: Config, token: Token | None) -> VehicleManager:
    return VehicleManager(
        region=config.region,
        brand=config.brand,
        username=config.username,
        password=config.password,
        pin=config.pin or "",
        language=config.language,
        token=token,
    )


class Session:
    def __init__(
        self, config: Config, manager_factory: ManagerFactory = default_manager_factory
    ) -> None:
        self._config = config
        self._factory = manager_factory
        self._manager: VehicleManager | None = None
        self._lock = threading.Lock()
        self._saved_token: dict[str, Any] | None = None

    def _get_manager(self) -> VehicleManager:
        if self._manager is None:
            token = load_token(self._config)
            self._saved_token = token.to_dict() if token is not None else None
            self._manager = self._factory(self._config, token)
        return self._manager

    def _persist_if_changed(self, manager: VehicleManager) -> None:
        token = manager.token
        if token is None:
            return
        current = token.to_dict()
        if current != self._saved_token:
            try:
                save_token(self._config, token)
            except Exception as exc:
                log.warning("Token save failed: %s", type(exc).__name__)
                return
            self._saved_token = current

    def _run_sync(
        self, fn: Callable[[VehicleManager], T], *, refresh: bool = True
    ) -> T:
        secrets = [self._config.password, self._config.pin]
        with self._lock:
            try:
                manager = self._get_manager()
                if refresh:
                    manager.check_and_refresh_token()
                try:
                    return fn(manager)
                finally:
                    self._persist_if_changed(manager)
            except Exception as exc:
                failure = to_tool_failure(exc, secrets)
                if failure is not exc:
                    log.warning("Call failed: %s", type(exc).__name__)
                raise failure from None

    async def call(self, fn: Callable[[VehicleManager], T]) -> T:
        return await asyncio.to_thread(self._run_sync, fn)

    def vehicle(self, manager: VehicleManager, vehicle_id: str) -> Vehicle:
        if vehicle_id in manager.vehicles:
            return manager.vehicles[vehicle_id]
        for v in manager.vehicles.values():
            if public_vehicle_id(v) == vehicle_id:
                return v
        raise ToolFailure(f"Unknown vehicle_id '{vehicle_id}'. Call list_vehicles.")

    async def send_otp(self, method: Literal["email", "sms"]) -> str:
        def work(manager: VehicleManager) -> str:
            if manager.otp_request is None:
                if manager.login() is True:
                    return "Already logged in. No passcode needed."
                if manager.otp_request is None:
                    raise ToolFailure(
                        "Login failed. Check BLUELINK_USERNAME and BLUELINK_PASSWORD."
                    )
            notify = OTP_NOTIFY_TYPE.EMAIL if method == "email" else OTP_NOTIFY_TYPE.SMS
            manager.send_otp(notify)
            return "Passcode sent by email." if method == "email" else "Passcode sent by SMS."

        return await asyncio.to_thread(self._run_sync, work, refresh=False)

    async def verify_otp(self, code: str) -> str:
        def work(manager: VehicleManager) -> str:
            if manager.otp_request is None:
                raise ToolFailure("No passcode is pending. Call send_otp first.")
            manager.verify_otp_and_complete_login(code)
            manager.otp_request = None
            return f"Logged in. {len(manager.vehicles)} vehicle(s) found."

        return await asyncio.to_thread(self._run_sync, work, refresh=False)
