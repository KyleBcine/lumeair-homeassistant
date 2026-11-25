"""The latest LumeAir firmware release, read from the LumeAir website.

The release list is the same public manifest the LumeAir app reads. Nothing
about your sensors is sent: Home Assistant only downloads the list. The
sensor itself checks each release's signature (made with LumeAir's release
key) before installing it, and downloads the firmware over HTTPS; see the
firmware's docs/PROTOCOL.md, POST /ota.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

RELEASE_PREFIX = "https://kylebcine.github.io/lumeair-site/firmware/"
MANIFEST_URL = RELEASE_PREFIX + "manifest.json"
CHECK_INTERVAL = timedelta(hours=6)
# The board current firmware runs on. Releases are signed for it, and the
# earlier board's firmware refuses them.
RELEASE_MODEL = "sen66"

_VERSION = re.compile(r"(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})")
_HEX = re.compile(r"[0-9a-fA-F]+")
_TIMEOUT = ClientTimeout(total=20)
_DATA_KEY = f"{DOMAIN}_firmware_releases"


def version_tuple(text: object) -> tuple[int, int, int] | None:
    """MAJOR.MINOR.PATCH as numbers (the firmware's own rules), or None."""
    if not isinstance(text, str):
        return None
    match = _VERSION.fullmatch(text)
    if match is None:
        return None
    parts = tuple(int(p) for p in match.groups())
    if max(parts) > 65535:
        return None
    return parts  # type: ignore[return-value]


@dataclass(frozen=True)
class FirmwareRelease:
    """One signed release, as the manifest describes it."""

    version: str
    url: str
    sha256: str
    signature: str
    notes: str


def parse_release(data: Any) -> FirmwareRelease | None:
    """The release in a manifest, or None when it's malformed. The sensor
    checks all of this again, and the signature, before installing."""
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    url = data.get("url")
    sha256 = data.get("sha256")
    signature = data.get("signature")
    notes = data.get("notes")
    if (
        version_tuple(version) is None
        or not isinstance(url, str)
        or not url.startswith(RELEASE_PREFIX)
        or not url.endswith(".bin")
        or any(c in url for c in "?#%")
        or ".." in url
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or not _HEX.fullmatch(sha256)
        or not isinstance(signature, str)
        or len(signature) != 128
        or not _HEX.fullmatch(signature)
    ):
        return None
    return FirmwareRelease(
        version=version,
        url=url,
        sha256=sha256.lower(),
        signature=signature.lower(),
        notes=notes.strip() if isinstance(notes, str) else "",
    )


class FirmwareReleaseCoordinator(DataUpdateCoordinator[FirmwareRelease | None]):
    """Checks the LumeAir website for the latest release every 6 hours. One is
    shared by every sensor. After a failed check the last release found
    stays."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Set up the check; it runs while any sensor's update entity exists."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN} firmware releases",
            update_interval=CHECK_INTERVAL,
        )

    async def _async_update_data(self) -> FirmwareRelease | None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(MANIFEST_URL, timeout=_TIMEOUT) as response:
                if response.status != 200:
                    raise UpdateFailed(f"{MANIFEST_URL}: HTTP {response.status}")
                data = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"{MANIFEST_URL}: {err}") from err
        release = parse_release(data)
        if release is None:
            raise UpdateFailed(f"{MANIFEST_URL}: not a valid release")
        return release


async def async_get_releases(hass: HomeAssistant) -> FirmwareReleaseCoordinator:
    """The shared release check, checked once when first needed. A website
    that can't be reached doesn't stop sensors from loading."""
    coordinator: FirmwareReleaseCoordinator | None = hass.data.get(_DATA_KEY)
    if coordinator is None:
        coordinator = FirmwareReleaseCoordinator(hass)
        hass.data[_DATA_KEY] = coordinator
        await coordinator.async_refresh()
    return coordinator
