"""Polls one LumeAir sensor."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CannotConnect, InvalidAuth, LumeAirClient
from .const import CONF_DEVICE_ID, DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type LumeAirConfigEntry = ConfigEntry[LumeAirCoordinator]


@dataclass(frozen=True)
class LumeAirData:
    """One poll of the sensor."""

    latest: dict[str, Any]
    # None on firmware without alerts (before 0.2.0).
    active_alerts: frozenset[str] | None
    rssi: int | None


class LumeAirCoordinator(DataUpdateCoordinator[LumeAirData]):
    """Reads the sensor every 30 s."""

    config_entry: LumeAirConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: LumeAirConfigEntry, client: LumeAirClient
    ) -> None:
        """Set up polling for entry's sensor."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> LumeAirData:
        try:
            latest = await self.client.latest()
            alerts = await self.client.active_alerts()
            rssi = await self.client.wifi_rssi()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except CannotConnect as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        self._update_firmware_version(latest.get("fw_version"))
        return LumeAirData(latest=latest, active_alerts=alerts, rssi=rssi)

    def _update_firmware_version(self, version: object) -> None:
        """Keep the device page's firmware version current after an update."""
        if not isinstance(version, str) or not version:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, self.config_entry.data[CONF_DEVICE_ID]),
            self.config_entry.entry_id,
        )
        if device is not None and device.sw_version != version:
            registry.async_update_device(device.id, sw_version=version)
