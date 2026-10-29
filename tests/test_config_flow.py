"""Adding sensors: discovery, pair code, reauth."""

from __future__ import annotations

from ipaddress import ip_address

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.lumeair.const import CONF_DEVICE_ID, DOMAIN

from .conftest import DEVICE_ID, HOST, TOKEN, mock_sensor, pair_code


def discovery(host: str = HOST) -> ZeroconfServiceInfo:
    """The sensor's mDNS announcement."""
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        hostname="lumeair-D4DB1C.local.",
        name="LumeAir-D4DB1C._airsense._tcp.local.",
        port=80,
        type="_airsense._tcp.local.",
        properties={
            "id": DEVICE_ID,
            "name": "LumeAir-D4DB1C",
            "path": "/metrics.json",
            "fw": "0.5.0",
            "api": "1",
        },
    )


async def test_discovered_sensor_is_paired(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Discovery asks for the pair code and names the device after the room."""
    mock_sensor(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=discovery()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"

    # Not a code, then another sensor's code.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pair_code": "hello"}
    )
    assert result["errors"] == {"base": "invalid_code"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pair_code": pair_code(device_id="AABBCCDDEEFF")}
    )
    assert result["errors"] == {"base": "wrong_sensor"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pair_code": pair_code()}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bedroom"
    assert result["data"] == {
        CONF_HOST: HOST,
        "port": 80,
        CONF_TOKEN: TOKEN,
        CONF_DEVICE_ID: DEVICE_ID,
    }


async def test_discovery_follows_a_new_address(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A sensor already added is updated, not offered again."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=discovery("192.168.4.77")
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == "192.168.4.77"


async def test_pair_code_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A refused key and an unreachable sensor say so."""
    mock_sensor(aioclient_mock, status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pair_code": pair_code()}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_sensor(aioclient_mock, status=500)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pair_code": pair_code()}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_added_by_pair_code_alone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The code carries the address; the sensor must be the one it names."""
    mock_sensor(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pair_code": pair_code(device_id="AABBCCDDEEFF")}
    )
    assert result["errors"] == {"base": "wrong_sensor"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pair_code": pair_code()}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == DEVICE_ID


async def test_reauth_takes_a_new_code(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """After the sensor is set up again, a new code replaces the key."""
    config_entry.add_to_hass(hass)
    mock_sensor(aioclient_mock)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pair_code": pair_code(device_id="AABBCCDDEEFF")}
    )
    assert result["errors"] == {"base": "wrong_sensor"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pair_code": pair_code(token="new-key")}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKEN] == "new-key"
