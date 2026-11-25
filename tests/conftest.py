"""Shared test fixtures: a fake sensor on the network."""

from __future__ import annotations

import base64
import hmac
import json
from typing import Any

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.lumeair.api import (
    AUTH_HEADER,
    LEGACY_AUTH_HEADER,
    sign,
    signed_text,
)
from custom_components.lumeair.const import CONF_DEVICE_ID, DOMAIN
from custom_components.lumeair.firmware import MANIFEST_URL, RELEASE_PREFIX

HOST = "192.168.4.45"
DEVICE_ID = "24EC4AD4DB1C"
TOKEN = "k1-secret"
BASE = f"http://{HOST}:80"

LATEST: dict[str, Any] = {
    "device_id": DEVICE_ID,
    "device_name": "LumeAir-D4DB1C",
    "fw_version": "0.5.0",
    "boot_count": 12,
    "reset_reason": "POWERON",
    "uptime_ms": 123456,
    "ip": HOST,
    "ts": 1761000000,
    "time_valid": True,
    "co2": 640,
    "voc": 101,
    "pm1_0": 3,
    "pm2_5": 5,
    "pm10": 6,
    "temp": 21.43,
    "humidity": 44.1,
    "pressure_hpa": 1013.25,
    "model": "sen66",
    "pm4_0": 6,
    "nox": 1,
}


# The release list on the LumeAir website, newer than LATEST's 0.5.0.
MANIFEST: dict[str, Any] = {
    "version": "0.8.0",
    "url": f"{RELEASE_PREFIX}lumeair-0.8.0.bin",
    "size": 1910352,
    "sha256": "ab" * 32,
    "signature": "cd" * 64,
    "notes": "Adds PM4.0, NOx and pressure to the sensor's history.",
    "released": "2026-11-24",
    "commit": "5da8c42",
}


def pair_code(
    *,
    host: str = HOST,
    token: str = TOKEN,
    device_id: str | None = DEVICE_ID,
    name: str | None = "Bedroom",
) -> str:
    """A pair code as the app makes it."""
    payload: dict[str, Any] = {
        "v": 1,
        "endpoint": f"http://{host}/metrics.json",
        "token": token,
    }
    if device_id is not None:
        payload["id"] = device_id
    if name is not None:
        payload["name"] = name
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


class FakeSensor:
    """A sensor's HTTP API, checking each request's key as the firmware does.

    With signs (firmware 0.7.0+), it serves /auth/clock and checks signatures;
    it also takes the plain key, as the firmware does, but counts it, since
    this integration must never send it to such a sensor. Without signs (older
    firmware), /auth/clock is 404 and only the plain key works.
    """

    def __init__(
        self,
        aioclient_mock: AiohttpClientMocker,
        *,
        latest: dict[str, Any],
        active: list[str],
        rssi: int,
        status: int,
        base: str,
        signs: bool,
        keys: tuple[str, ...],
    ) -> None:
        self._mock = aioclient_mock
        self.latest = latest
        self.signs = signs
        self.keys = keys
        self.boot = "00112233aabbccdd"
        self.time = 1000
        self.plain_keys = 0
        self.signed = 0
        self._status = status
        self._bodies = {
            "/latest": latest,
            "/alerts": {"time_valid": True, "active": active, "events": []},
            "/diag/wifi": {"connected": True, "rssi_dbm": rssi},
        }
        # Firmware updates: what POST /ota answers, the GET /ota replies in
        # turn (the last one repeats), and the forms posted.
        self.ota_reply: tuple[int, dict[str, Any]] = (202, {"state": "downloading"})
        self.ota_states: list[dict[str, Any]] = [{"state": "idle", "progress": 0}]
        self.ota_posts: list[dict[str, str]] = []
        # The version the sensor runs after restarting into an update.
        self.installs: str | None = None
        aioclient_mock.get(f"{base}/auth/clock", side_effect=self._clock)
        for path in ("/latest", "/alerts", "/diag/wifi"):
            aioclient_mock.get(f"{base}{path}", side_effect=self._serve)
        aioclient_mock.get(f"{base}/ota", side_effect=self._ota_status)
        aioclient_mock.post(f"{base}/ota", side_effect=self._ota_start)

    def reboot(self) -> None:
        """A restart: a new boot ID and the clock back near zero."""
        self.boot = "ffeeddccbbaa9988"
        self.time = 5

    def _reply(
        self, url: URL, status: int, body: Any = None
    ) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse("get", url, status=status, json=body)

    async def _clock(
        self, method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        if not self.signs:
            return self._reply(url, 404)
        return self._reply(url, 200, {"v": 1, "boot": self.boot, "t": self.time})

    def _access(
        self,
        url: URL,
        headers: dict[str, str],
        method: str = "GET",
        form: list[tuple[str, str]] | None = None,
    ) -> str:
        """ "ok", "stale" or "refused", as the firmware decides."""
        if self.signs and AUTH_HEADER in headers:
            fields = dict(p.split("=", 1) for p in headers[AUTH_HEADER].split(";"))
            if fields.get("v") != "1":
                return "refused"
            if fields["b"] != self.boot or abs(int(fields["t"]) - self.time) > 60:
                return "stale"
            text = signed_text(
                method,
                url.path,
                fields["b"],
                int(fields["t"]),
                fields["n"],
                list(url.query.items()),
                form or [],
            )
            if any(hmac.compare_digest(sign(k, text), fields["s"]) for k in self.keys):
                self.signed += 1
                return "ok"
            return "refused"
        if LEGACY_AUTH_HEADER in headers:
            self.plain_keys += 1
            return "ok" if headers[LEGACY_AUTH_HEADER] in self.keys else "refused"
        return "refused"

    async def _serve(
        self, method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        # The mocker records each call, headers included, before answering it.
        headers = self._mock.mock_calls[-1][3] or {}
        access = self._access(url, headers)
        if access == "stale":
            return self._reply(
                url, 401, {"error": "stale_auth", "boot": self.boot, "t": self.time}
            )
        if access == "refused":
            return self._reply(url, 401, {"error": "unauthorized"})
        if self._status != 200:
            return self._reply(url, self._status)
        body = self._bodies[url.path]
        if url.path == "/latest":
            body = self.latest
        return self._reply(url, 200, body)

    def _refusal(self, url: URL, access: str) -> AiohttpClientMockResponse | None:
        if access == "stale":
            return self._reply(
                url, 401, {"error": "stale_auth", "boot": self.boot, "t": self.time}
            )
        if access == "refused":
            return self._reply(url, 401, {"error": "unauthorized"})
        return None

    async def _ota_start(
        self, method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        headers = self._mock.mock_calls[-1][3] or {}
        form = [(str(k), str(v)) for k, v in data]
        refusal = self._refusal(url, self._access(url, headers, "POST", form))
        if refusal is not None:
            return refusal
        self.ota_posts.append(dict(form))
        status, body = self.ota_reply
        return self._reply(url, status, body)

    async def _ota_status(
        self, method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        headers = self._mock.mock_calls[-1][3] or {}
        refusal = self._refusal(url, self._access(url, headers))
        if refusal is not None:
            return refusal
        state = self.ota_states.pop(0) if len(self.ota_states) > 1 else self.ota_states[0]
        if state.get("state") == "rebooting" and self.installs is not None:
            # It restarts into the new version: a new boot and clock.
            self.latest = {**self.latest, "fw_version": self.installs}
            self.reboot()
        return self._reply(url, 200, {"running": self.latest["fw_version"], **state})


def mock_sensor(
    aioclient_mock: AiohttpClientMocker,
    *,
    latest: dict[str, Any] | None = None,
    active: list[str] | None = None,
    rssi: int = -58,
    status: int = 200,
    base: str = BASE,
    signs: bool = True,
    keys: tuple[str, ...] = (TOKEN, "new-key"),
    release: dict[str, Any] | None = MANIFEST,
) -> FakeSensor:
    """Answer the sensor's endpoints at base, and the LumeAir website's
    release list (release; None for a website that can't be reached). A
    status of 401 is a sensor that refuses every key (set up again since)."""
    aioclient_mock.clear_requests()
    if release is None:
        aioclient_mock.get(MANIFEST_URL, status=503)
    else:
        aioclient_mock.get(MANIFEST_URL, json=release)
    return FakeSensor(
        aioclient_mock,
        latest=latest or LATEST,
        active=active or [],
        rssi=rssi,
        status=status,
        base=base,
        signs=signs,
        keys=() if status == 401 else keys,
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/lumeair in every test."""


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A paired sensor."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        unique_id=DEVICE_ID,
        data={
            CONF_HOST: HOST,
            CONF_PORT: 80,
            CONF_TOKEN: TOKEN,
            CONF_DEVICE_ID: DEVICE_ID,
        },
    )
