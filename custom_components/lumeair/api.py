"""A small client for the LumeAir sensor's local HTTP API.

The API is described in the firmware's docs/PROTOCOL.md. Nothing leaves the
home network.

Firmware 0.7.0+ takes signed requests: the access key itself never crosses
the network. Each request carries an HMAC-SHA256 signature made with it, over
the method, path and parameters, a random nonce and the sensor's clock (from
GET /auth/clock, which needs no key). Older firmware only knows the plain key
in the X-AirSense-Token header. Once a sensor has answered /auth/clock, this
client never sends it the plain key again, so a fake "not found" on the
network can't make it fall back.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError, ClientSession, ClientTimeout

if TYPE_CHECKING:
    from .firmware import FirmwareRelease

AUTH_HEADER = "X-LumeAir-Auth"
LEGACY_AUTH_HEADER = "X-AirSense-Token"

# How long to keep using the plain key with firmware that has no
# /auth/clock before asking again, in case it has been updated since.
LEGACY_RECHECK_S = 300.0

_TIMEOUT = ClientTimeout(total=10)


class LumeAirError(Exception):
    """The sensor couldn't be read."""


class CannotConnect(LumeAirError):
    """The sensor didn't answer, or answered with something unexpected."""


class InvalidAuth(LumeAirError):
    """The sensor refused the access key."""


class UpdateRefused(LumeAirError):
    """The sensor didn't start a firmware update. code is its reason
    (docs/PROTOCOL.md, POST /ota): not_newer, busy, on_trial, bad_signature,
    no_memory, ..., or unsupported for firmware before 0.4.0."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def signed_text(
    method: str,
    path: str,
    boot: str,
    sensor_time: int,
    nonce: str,
    query: Sequence[tuple[str, str]],
    form: Sequence[tuple[str, str]] = (),
) -> bytes:
    """The text a request's signature covers (docs/PROTOCOL.md): query
    parameters, then form fields, in the order they are sent."""
    out = bytearray(b"lumeair-request-v1\n")
    for part in (method, path, boot, str(sensor_time), nonce):
        out += part.encode() + b"\n"
    for kind, params in ((b"q", query), (b"f", form)):
        for name, value in params:
            raw_name = name.encode()
            raw_value = value.encode()
            out += b"%s%d:%s%d:%s\n" % (
                kind,
                len(raw_name),
                raw_name,
                len(raw_value),
                raw_value,
            )
    return bytes(out)


def sign(token: str, text: bytes) -> str:
    """The signature of text with the access key."""
    return _b64url(hmac.new(token.encode(), text, hashlib.sha256).digest())


class LumeAirClient:
    """Reads one sensor."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        port: int,
        token: str,
        *,
        signs: bool = False,
    ) -> None:
        """Set up the client for the sensor at host:port. With signs, the
        sensor is already known to take signed requests."""
        self._session = session
        self._base = f"http://{host}:{port}"
        self._token = token.strip()
        self._signs = signs
        # The sensor's clock: boot ID, its time, and our monotonic time then.
        self._clock: tuple[str, int, float] | None = None
        self._legacy_until = 0.0

    @property
    def signs(self) -> bool:
        """True once the sensor has shown it takes signed requests."""
        return self._signs

    def _set_clock(self, data: dict[str, Any]) -> bool:
        boot = data.get("boot")
        sensor_time = data.get("t")
        if not isinstance(boot, str) or not isinstance(sensor_time, int):
            return False
        self._clock = (boot, sensor_time, time.monotonic())
        self._signs = True
        return True

    async def _sync_clock(self) -> None:
        """Reads the sensor's clock; on firmware without one, switches to the
        plain key unless the sensor is known to sign."""
        try:
            async with self._session.get(
                f"{self._base}/auth/clock", timeout=_TIMEOUT
            ) as response:
                if response.status == 404 and not self._signs:
                    self._legacy_until = time.monotonic() + LEGACY_RECHECK_S
                    return
                if response.status != 200:
                    raise CannotConnect(f"/auth/clock: HTTP {response.status}")
                data = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise CannotConnect(f"/auth/clock: {err}") from err
        if not isinstance(data, dict) or not self._set_clock(data):
            raise CannotConnect("/auth/clock: unexpected reply")

    def _headers(
        self,
        method: str,
        path: str,
        query: Sequence[tuple[str, str]],
        form: Sequence[tuple[str, str]] = (),
    ) -> dict[str, str]:
        if self._clock is None:
            return {LEGACY_AUTH_HEADER: self._token}
        boot, sensor_time, at = self._clock
        now = sensor_time + int(time.monotonic() - at)
        # A fresh nonce each time: the sensor refuses a POST nonce it has
        # already seen.
        nonce = _b64url(secrets.token_bytes(16))
        text = signed_text(method, path, boot, now, nonce, query, form)
        signature = sign(self._token, text)
        return {AUTH_HEADER: f"v=1;b={boot};t={now};n={nonce};s={signature}"}

    async def _get(
        self,
        path: str,
        query: list[tuple[str, str]] | None = None,
        *,
        optional: bool = False,
    ) -> dict[str, Any] | None:
        """GET path as JSON. With optional, older firmware's 404 is None."""
        query = query or []
        for attempt in range(2):
            if self._clock is None and time.monotonic() >= self._legacy_until:
                await self._sync_clock()
            try:
                async with self._session.get(
                    f"{self._base}{path}",
                    params=query or None,
                    headers=self._headers("GET", path, query),
                    timeout=_TIMEOUT,
                ) as response:
                    status = response.status
                    data = (
                        await response.json(content_type=None)
                        if status in (200, 401)
                        else None
                    )
            except (ClientError, TimeoutError, ValueError) as err:
                raise CannotConnect(f"{path}: {err}") from err
            if status == 401:
                # A restart since the last sync (or drift): sync to the clock
                # the reply carries and sign again, once.
                if (
                    attempt == 0
                    and self._clock is not None
                    and isinstance(data, dict)
                    and data.get("error") == "stale_auth"
                    and self._set_clock(data)
                ):
                    continue
                raise InvalidAuth
            if optional and status == 404:
                return None
            if status != 200:
                raise CannotConnect(f"{path}: HTTP {status}")
            if not isinstance(data, dict):
                raise CannotConnect(f"{path}: unexpected reply")
            return data
        raise InvalidAuth

    async def _post_form(
        self, path: str, form: list[tuple[str, str]]
    ) -> tuple[int, dict[str, Any] | None]:
        """POST form fields to path; the status and the JSON reply, if any.
        Signed like _get, with the same retry after a sensor restart."""
        for attempt in range(2):
            if self._clock is None and time.monotonic() >= self._legacy_until:
                await self._sync_clock()
            try:
                async with self._session.post(
                    f"{self._base}{path}",
                    data=form,
                    headers=self._headers("POST", path, [], form),
                    timeout=_TIMEOUT,
                ) as response:
                    status = response.status
                    try:
                        data = await response.json(content_type=None)
                    except ValueError:
                        data = None
            except (ClientError, TimeoutError) as err:
                raise CannotConnect(f"{path}: {err}") from err
            if status == 401:
                if (
                    attempt == 0
                    and self._clock is not None
                    and isinstance(data, dict)
                    and data.get("error") == "stale_auth"
                    and self._set_clock(data)
                ):
                    continue
                raise InvalidAuth
            return status, data if isinstance(data, dict) else None
        raise InvalidAuth

    async def start_update(self, release: FirmwareRelease) -> None:
        """Asks the sensor to install release (POST /ota). The sensor checks
        the release signature itself, then downloads and installs it."""
        status, data = await self._post_form(
            "/ota",
            [
                ("version", release.version),
                ("url", release.url),
                ("sha256", release.sha256),
                ("signature", release.signature),
            ],
        )
        if status == 202:
            return
        if status == 404:
            raise UpdateRefused("unsupported")
        error = data.get("error") if data else None
        if status in (400, 409, 503) and isinstance(error, str):
            raise UpdateRefused(error)
        raise CannotConnect(f"/ota: HTTP {status}")

    async def update_status(self) -> dict[str, Any]:
        """The sensor's latest firmware update (GET /ota): state, progress,
        error, running version."""
        return await self._get("/ota") or {}

    async def latest(self) -> dict[str, Any]:
        """Every current reading, plus the device ID and firmware version."""
        return await self._get("/latest") or {}

    async def active_alerts(self) -> frozenset[str] | None:
        """Metrics above the sensor's alert thresholds right now; None on
        firmware before 0.2.0, which has no alerts."""
        data = await self._get("/alerts", [("limit", "1")], optional=True)
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
