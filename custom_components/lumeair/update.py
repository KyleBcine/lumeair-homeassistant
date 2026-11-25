"""LumeAir firmware updates, installed from Home Assistant.

The same updates the LumeAir app offers: the latest release on the LumeAir
website (firmware.py), passed to the sensor, which checks its signature,
downloads it, installs it and restarts. A new version that doesn't work is
rolled back by the sensor itself.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CannotConnect, InvalidAuth, LumeAirClient, UpdateRefused
from .const import DOMAIN
from .coordinator import LumeAirConfigEntry, LumeAirCoordinator
from .entity import LumeAirEntity
from .firmware import (
    RELEASE_MODEL,
    FirmwareRelease,
    FirmwareReleaseCoordinator,
    async_get_releases,
)

PARALLEL_UPDATES = 1

# How often the install is checked on, and how long each part may take: the
# download is about a minute on typical Wi-Fi, the restart a few seconds.
POLL_INTERVAL_S = 2.0
DOWNLOAD_TIMEOUT_S = 600.0
RESTART_TIMEOUT_S = 180.0

# The sensor's reasons for not starting (docs/PROTOCOL.md, POST /ota) that
# have their own message; anything else gets a general one.
_REFUSALS = {"not_newer", "busy", "on_trial", "bad_signature", "no_memory", "unsupported"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LumeAirConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensor's firmware update entity."""
    releases = await async_get_releases(hass)
    async_add_entities([LumeAirFirmwareUpdate(entry.runtime_data, releases)])


def _error(key: str, **placeholders: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


class LumeAirFirmwareUpdate(LumeAirEntity, UpdateEntity):
    """The sensor's firmware: installed, latest, and installing it."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(
        self, coordinator: LumeAirCoordinator, releases: FirmwareReleaseCoordinator
    ) -> None:
        """Set up the entity for coordinator's sensor."""
        super().__init__(coordinator, "firmware")
        self._releases = releases

    async def async_added_to_hass(self) -> None:
        """Also follow the website's release check."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._releases.async_add_listener(self._handle_coordinator_update)
        )

    @property
    def _release(self) -> FirmwareRelease | None:
        """The latest release, if it's for this sensor's board."""
        if self.coordinator.data.latest.get("model") != RELEASE_MODEL:
            return None
        return self._releases.data

    @property
    def installed_version(self) -> str | None:
        """The firmware the sensor runs."""
        version = self.coordinator.data.latest.get("fw_version")
        return version if isinstance(version, str) else None

    @property
    def latest_version(self) -> str | None:
        """The latest release for this sensor; the installed version when
        there's none for it (so nothing is offered)."""
        release = self._release
        return release.version if release is not None else self.installed_version

    @property
    def release_summary(self) -> str | None:
        """The release's notes, as the app shows them."""
        release = self._release
        return (release.notes or None) if release is not None else None

    async def async_release_notes(self) -> str | None:
        """The release's notes."""
        return self.release_summary

    @callback
    def _set_progress(self, percentage: int | None) -> None:
        # With PROGRESS, in_progress is ours to set; Home Assistant clears it
        # when async_install returns.
        self._attr_in_progress = True
        self._attr_update_percentage = percentage
        self.async_write_ha_state()

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install the latest release and wait until the sensor runs it."""
        release = self._release
        if release is None:
            raise _error("update_no_release")
        client = self.coordinator.client
        try:
            await client.start_update(release)
        except UpdateRefused as err:
            if err.code in _REFUSALS:
                raise _error(f"update_refused_{err.code}") from err
            raise _error("update_refused", reason=err.code) from err
        except InvalidAuth as err:
            raise _error("invalid_auth") from err
        except CannotConnect as err:
            raise _error("cannot_connect", error=str(err)) from err

        try:
            await self._follow_download(client, release)
            await self._wait_for_version(release)
        finally:
            self._attr_update_percentage = None

    async def _follow_download(
        self, client: LumeAirClient, release: FirmwareRelease
    ) -> None:
        """Reports progress until the sensor restarts into the new version."""
        self._set_progress(0)
        deadline = time.monotonic() + DOWNLOAD_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL_S)
            try:
                status = await client.update_status()
            except InvalidAuth as err:
                raise _error("invalid_auth") from err
            except CannotConnect:
                # Most likely restarting already: it only says "rebooting"
                # for about 3 s.
                return
            state = status.get("state")
            if state == "failed":
                raise _error("update_failed", reason=str(status.get("error") or "unknown"))
            if state == "rebooting" or status.get("running") == release.version:
                self._set_progress(100)
                return
            progress = status.get("progress")
            if isinstance(progress, int) and not isinstance(progress, bool):
                self._set_progress(max(0, min(progress, 99)))
        raise _error("update_timeout")

    async def _wait_for_version(self, release: FirmwareRelease) -> None:
        """Waits until the sensor is back and reports the new version."""
        deadline = time.monotonic() + RESTART_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL_S)
            await self.coordinator.async_refresh()
            if (
                self.coordinator.last_update_success
                and self.coordinator.data.latest.get("fw_version") == release.version
            ):
                return
        raise _error("update_not_installed", version=release.version)
