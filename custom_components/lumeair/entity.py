"""The base for LumeAir entities: one device per sensor."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, DOMAIN, MANUFACTURER, MODEL
from .coordinator import LumeAirCoordinator


class LumeAirEntity(CoordinatorEntity[LumeAirCoordinator]):
    """An entity on a LumeAir sensor's device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LumeAirCoordinator, key: str) -> None:
        """Set up the entity named by key."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_{key}"
        version = coordinator.data.latest.get("fw_version")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            serial_number=device_id,
            sw_version=version if isinstance(version, str) else None,
        )
