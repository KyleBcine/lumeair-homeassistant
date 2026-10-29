"""A small client for the LumeAir sensor's local HTTP API.

The API is described in the firmware's docs/PROTOCOL.md. Every request
carries the sensor's access key; nothing leaves the home network.
"""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout


class LumeAirError(Exception):
    """The sensor couldn't be read."""


class CannotConnect(LumeAirError):
    """The sensor didn't answer, or answered with something unexpected."""


class InvalidAuth(LumeAirError):
    """The sensor refused the access key."""


class LumeAirClient:
    """Reads one sensor."""

    def __init__(
        self, session: ClientSession, host: str, port: int, token: str
    ) -> None:
        """Set up the client for the sensor at host:port."""
        self._session = session
        self._base = f"http://{host}:{port}"
        self._token = token

    async def _get(self, path: str, *, optional: bool = False) -> dict[str, Any] | None:
        """GET path as JSON. With optional, older firmware's 404 is None."""
        try:
            async with self._session.get(
                f"{self._base}{path}",
                headers={"X-AirSense-Token": self._token},
                timeout=ClientTimeout(total=10),
            ) as response:
                if response.status == 401:
                    raise InvalidAuth
                if optional and response.status == 404:
                    return None
                if response.status != 200:
                    raise CannotConnect(f"{path}: HTTP {response.status}")
                data = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise CannotConnect(f"{path}: {err}") from err
        if not isinstance(data, dict):
            raise CannotConnect(f"{path}: unexpected reply")
        return data

    async def latest(self) -> dict[str, Any]:
        """Every current reading, plus the device ID and firmware version."""
        return await self._get("/latest") or {}

    async def active_alerts(self) -> frozenset[str] | None:
        """Metrics above the sensor's alert thresholds right now; None on
        firmware before 0.2.0, which has no alerts."""
        data = await self._get("/alerts?limit=1", optional=True)
        if data is None:
            return None
        active = data.get("active")
        return (
            frozenset(m for m in active if isinstance(m, str))
            if isinstance(active, list)
            else frozenset()
        )

    async def wifi_rssi(self) -> int | None:
        """Wi-Fi signal in dBm; None when not connected or not reported."""
        data = await self._get("/diag/wifi", optional=True)
        rssi = None if data is None else data.get("rssi_dbm")
        return rssi if isinstance(rssi, int) and rssi != 0 else None
