from __future__ import annotations

import datetime as dt
import threading
import time

from hyundai_kia_connect_api.const import ORDER_STATUS
from hyundai_kia_connect_api.Token import Token


def make_token(access: str = "tok") -> Token:
    return Token(
        username="u@x.com",
        password="pw",
        access_token=access,
        refresh_token="r",
        device_id="d",
        valid_until=dt.datetime(2030, 1, 1),
        pin="1234",
    )


class FakeManager:
    def __init__(self, token: Token | None = None):
        self.token = token
        self.vehicles: dict = {}
        self.otp_request = None
        self.refresh_calls = 0
        self.refresh_delay = 0.0
        self.refresh_effect = None
        self.login_result: object = True
        self.login_calls = 0
        self.sent_otp = None
        self.verified_code = None
        self._active = 0
        self.max_active = 0
        self._guard = threading.Lock()

    def check_and_refresh_token(self):
        with self._guard:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            self.refresh_calls += 1
            if self.refresh_delay:
                time.sleep(self.refresh_delay)
            if self.refresh_effect:
                self.refresh_effect(self)
        finally:
            with self._guard:
                self._active -= 1

    def login(self):
        self.login_calls += 1
        if self.login_result is True:
            self.token = make_token("logged-in")
        elif self.login_result is not False:
            self.otp_request = self.login_result
        return self.login_result

    def send_otp(self, notify_type):
        self.sent_otp = notify_type

    def verify_otp_and_complete_login(self, code):
        self.verified_code = code
        self.token = make_token("otp-token")
        self.vehicles = {"v1": object()}


class FakeFactory:
    """Records the Token | None it received; hands back one FakeManager."""

    def __init__(self, manager: FakeManager | None = None):
        self.manager = manager or FakeManager()
        self.calls = 0
        self.received_token = "unset"

    def __call__(self, config, token):
        self.calls += 1
        self.received_token = token
        if self.manager.token is None:
            self.manager.token = token
        return self.manager


class FakeCommandManager(FakeManager):
    """FakeManager that records vehicle commands sent by tools."""

    def __init__(self, token: Token | None = None):
        super().__init__(token or make_token())
        self.commands: list[tuple] = []
        self.unlock_calls = 0
        self.return_none = False

    def _record(self, *call):
        self.commands.append(call)
        return None if self.return_none else "act-1"

    def unlock(self, vehicle_id):
        self.unlock_calls += 1
        return self._record("unlock", vehicle_id)

    def lock(self, vehicle_id):
        return self._record("lock", vehicle_id)

    def start_climate(self, vehicle_id, options):
        return self._record("start_climate", vehicle_id, options)

    def set_windows_state(self, vehicle_id, options):
        return self._record("set_windows_state", vehicle_id, options)

    def start_charge(self, vehicle_id):
        return self._record("start_charge", vehicle_id)

    def set_charge_limits(self, vehicle_id, ac, dc):
        return self._record("set_charge_limits", vehicle_id, ac, dc)

    def schedule_charging_and_climate(self, vehicle_id, options):
        return self._record("schedule_charging_and_climate", vehicle_id, options)

    def set_navigation(self, vehicle_id, poi_list):
        return self._record("set_navigation", vehicle_id, poi_list)

    def update_vehicle_with_cached_state(self, vehicle_id):
        self.commands.append(("cached", vehicle_id))

    def force_refresh_vehicle_state(self, vehicle_id):
        self.commands.append(("force", vehicle_id))

    def check_action_status(self, vehicle_id, action_id, synchronous=False, timeout=120):
        self.commands.append(("check", vehicle_id, action_id, synchronous, timeout))
        return ORDER_STATUS.SUCCESS
