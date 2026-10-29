"""LumeAir air-quality sensors, read over the home network."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LumeAirClient
from .coordinator import LumeAirConfigEntry, LumeAirCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: LumeAirConfigEntry) -> bool:
    """Start reading one sensor."""
    client = LumeAirClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_TOKEN],
    )
    coordinator = LumeAirCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LumeAirConfigEntry) -> bool:
    """Stop reading one sensor."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
