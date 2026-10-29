"""Reading a paired sensor: entities, outages, a refused key, diagnostics."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.lumeair.const import DOMAIN, SCAN_INTERVAL
from custom_components.lumeair.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import DEVICE_ID, LATEST, TOKEN, mock_sensor


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_readings_and_device(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Every reading appears on one device named after the room."""
    mock_sensor(aioclient_mock, active=["co2"])
    await setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    expected = {
        "sensor.bedroom_air_quality": "good",
        "sensor.bedroom_carbon_dioxide": "640",
        "sensor.bedroom_pm1": "3",
        "sensor.bedroom_pm2_5": "5",
        "sensor.bedroom_pm10": "6",
        "sensor.bedroom_voc_index": "101",
        "sensor.bedroom_temperature": "21.43",
        "sensor.bedroom_humidity": "44.1",
        "sensor.bedroom_atmospheric_pressure": "1013.25",
        "binary_sensor.bedroom_co2_alert": STATE_ON,
        "binary_sensor.bedroom_pm2_5_alert": STATE_OFF,
    }
    for entity_id, value in expected.items():
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state == value, entity_id
    # Diagnostic and disabled until wanted.
    assert hass.states.get("sensor.bedroom_wi_fi_signal") is None

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, DEVICE_ID), config_entry.entry_id
    )
    assert device is not None
    assert (device.name, device.sw_version) == ("Bedroom", "0.5.0")


async def test_not_yet_measured_is_unknown(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Right after the sensor starts: no CO2, VOC or particles yet."""
    mock_sensor(
        aioclient_mock,
        latest={
            **LATEST,
            "co2": 0,
            "voc": 0,
            "pm1_0": None,
            "pm2_5": None,
            "pm10": None,
        },
    )
    await setup(hass, config_entry)
    for entity_id in (
        "sensor.bedroom_carbon_dioxide",
        "sensor.bedroom_voc_index",
        "sensor.bedroom_pm2_5",
        "sensor.bedroom_air_quality",
    ):
        assert hass.states.get(entity_id).state == STATE_UNKNOWN, entity_id


async def test_outage_and_firmware_update(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Unplugged: unavailable. Back on new firmware: values and version."""
    mock_sensor(aioclient_mock)
    await setup(hass, config_entry)

    mock_sensor(aioclient_mock, status=500)
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.bedroom_carbon_dioxide").state == STATE_UNAVAILABLE

    mock_sensor(aioclient_mock, latest={**LATEST, "co2": 900, "fw_version": "0.5.1"})
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.bedroom_carbon_dioxide").state == "900"
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, DEVICE_ID), config_entry.entry_id
    )
    assert device.sw_version == "0.5.1"


async def test_refused_key_asks_to_pair_again(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A sensor set up again refuses the old key: Home Assistant asks for a
    new pair code."""
    mock_sensor(aioclient_mock, status=401)
    await setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_older_firmware_without_alerts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Firmware before 0.2.0 has no /alerts: readings only."""
    mock_sensor(aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get("http://192.168.4.45:80/latest", json=LATEST)
    aioclient_mock.get("http://192.168.4.45:80/alerts?limit=1", status=404)
    aioclient_mock.get("http://192.168.4.45:80/diag/wifi", status=404)
    await setup(hass, config_entry)
    assert hass.states.get("sensor.bedroom_carbon_dioxide").state == "640"
    assert hass.states.get("binary_sensor.bedroom_co2_alert") is None


async def test_diagnostics_hide_the_key(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The access key and addresses are redacted."""
    mock_sensor(aioclient_mock, active=["pm25"])
    await setup(hass, config_entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    text = str(diagnostics)
    assert TOKEN not in text
    assert "192.168.4.45" not in text
    assert diagnostics["data"]["active_alerts"] == ["pm25"]
    assert diagnostics["data"]["latest"]["co2"] == 640
