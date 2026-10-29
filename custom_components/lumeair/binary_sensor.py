"""LumeAir alerts: on while a reading is above the sensor's threshold.

The thresholds are the ones set in the LumeAir app, which every phone and
Home Assistant share; the sensor decides when an alert starts and ends.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ALERT_METRICS
from .coordinator import LumeAirConfigEntry, LumeAirCoordinator
from .entity import LumeAirEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LumeAirConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a sensor's alerts, when its firmware has them (0.2.0+)."""
    coordinator = entry.runtime_data
    if coordinator.data.active_alerts is None:
        return
    async_add_entities(LumeAirAlert(coordinator, metric) for metric in ALERT_METRICS)


class LumeAirAlert(LumeAirEntity, BinarySensorEntity):
    """Whether one metric is in alert."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: LumeAirCoordinator, metric: str) -> None:
        """Set up the alert for metric."""
        super().__init__(coordinator, f"{metric}_alert")
        self._metric = metric
        self._attr_translation_key = f"{metric}_alert"

    @property
    def is_on(self) -> bool | None:
        """On while the sensor reports this metric's alert as active."""
        active = self.coordinator.data.active_alerts
        return None if active is None else self._metric in active
