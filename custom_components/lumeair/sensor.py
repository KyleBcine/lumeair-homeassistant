"""LumeAir readings: CO2, particles, VOC, comfort and the overall rating."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .air_quality import RATINGS, air_quality, pollutant_value
from .coordinator import LumeAirConfigEntry, LumeAirCoordinator, LumeAirData
from .entity import LumeAirEntity

# Each poll is independent: the sensor itself does no batching.
PARALLEL_UPDATES = 0


def _number(key: str) -> Callable[[LumeAirData], StateType]:
    def read(data: LumeAirData) -> StateType:
        value = data.latest.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value

    return read


def _pollutant(key: str) -> Callable[[LumeAirData], StateType]:
    return lambda data: pollutant_value(data.latest, key)


def _comfort(key: str) -> Callable[[LumeAirData], StateType]:
    """Temperature or humidity. The sensor reports -1.70 °C and 2.00 % (its
    calibration applied to nothing) while its humidity sensor is failing."""
    read = _number(key)

    def comfort(data: LumeAirData) -> StateType:
        latest: dict[str, Any] = data.latest
        if latest.get("temp") == -1.7 and latest.get("humidity") == 2.0:
            return None
        return read(data)

    return comfort


@dataclass(frozen=True, kw_only=True)
class LumeAirSensorDescription(SensorEntityDescription):
    """A reading and how to find it in a poll."""

    value_fn: Callable[[LumeAirData], StateType]


SENSORS: tuple[LumeAirSensorDescription, ...] = (
    LumeAirSensorDescription(
        key="air_quality",
        translation_key="air_quality",
        device_class=SensorDeviceClass.ENUM,
        options=RATINGS,
        value_fn=lambda data: air_quality(data.latest),
    ),
    LumeAirSensorDescription(
        key="co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_pollutant("co2"),
    ),
    LumeAirSensorDescription(
        key="pm1",
        device_class=SensorDeviceClass.PM1,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_number("pm1_0"),
    ),
    LumeAirSensorDescription(
        key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_pollutant("pm2_5"),
    ),
    LumeAirSensorDescription(
        key="pm10",
        device_class=SensorDeviceClass.PM10,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_pollutant("pm10"),
    ),
    # An index relative to the room's usual air (about 100), not a
    # concentration, so it has no device class or unit.
    LumeAirSensorDescription(
        key="voc_index",
        translation_key="voc_index",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_pollutant("voc"),
    ),
    LumeAirSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_comfort("temp"),
    ),
    LumeAirSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_comfort("humidity"),
    ),
    LumeAirSensorDescription(
        key="pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_number("pressure_hpa"),
    ),
    LumeAirSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.rssi,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LumeAirConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a sensor's readings."""
    coordinator = entry.runtime_data
    async_add_entities(
        LumeAirSensor(coordinator, description) for description in SENSORS
    )


class LumeAirSensor(LumeAirEntity, SensorEntity):
    """One reading."""

    entity_description: LumeAirSensorDescription

    def __init__(
        self,
        coordinator: LumeAirCoordinator,
        description: LumeAirSensorDescription,
    ) -> None:
        """Set up the reading described by description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """The current reading; None (unknown) before the sensor has one."""
        return self.entity_description.value_fn(self.coordinator.data)
