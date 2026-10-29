"""Shared test fixtures: a fake sensor on the network."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.lumeair.const import CONF_DEVICE_ID, DOMAIN

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


def mock_sensor(
    aioclient_mock: AiohttpClientMocker,
    *,
    latest: dict[str, Any] | None = None,
    active: list[str] | None = None,
    rssi: int = -58,
    status: int = 200,
    base: str = BASE,
) -> None:
    """Answer the sensor's endpoints at base."""
    aioclient_mock.clear_requests()
    if status != 200:
        for path in ("/latest", "/alerts?limit=1", "/diag/wifi"):
            aioclient_mock.get(f"{base}{path}", status=status)
        return
    aioclient_mock.get(f"{base}/latest", json=latest or LATEST)
    aioclient_mock.get(
        f"{base}/alerts?limit=1",
        json={"time_valid": True, "active": active or [], "events": []},
    )
    aioclient_mock.get(f"{base}/diag/wifi", json={"connected": True, "rssi_dbm": rssi})


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
