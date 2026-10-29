"""Adding a LumeAir sensor: found on the network, paired with its pair code."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import CannotConnect, InvalidAuth, LumeAirClient
from .const import CONF_DEVICE_ID, DOMAIN
from .pair_code import PairCode, decode_pair_code

CONF_PAIR_CODE = "pair_code"

PAIR_SCHEMA = vol.Schema({vol.Required(CONF_PAIR_CODE): str})


class LumeAirConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pairs Home Assistant with one sensor."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing discovered."""
        self._host: str | None = None
        self._port = 80
        self._name: str | None = None

    async def _check(
        self, host: str, port: int, code: PairCode, errors: dict[str, str]
    ) -> str | None:
        """Read the sensor at host:port with code's key. Returns its device
        ID, or None after adding to errors."""
        client = LumeAirClient(
            async_get_clientsession(self.hass), host, port, code.token
        )
        try:
            latest = await client.latest()
        except InvalidAuth:
            errors["base"] = "invalid_auth"
            return None
        except CannotConnect:
            errors["base"] = "cannot_connect"
            return None
        device_id = latest.get("device_id")
        if not isinstance(device_id, str) or not device_id:
            errors["base"] = "cannot_connect"
            return None
        # A code for another sensor (or an address now used by another one).
        if code.device_id and code.device_id.upper() != device_id.upper():
            errors["base"] = "wrong_sensor"
            return None
        return device_id.upper()

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """A sensor announced itself on the network."""
        device_id = discovery_info.properties.get("id")
        if not device_id:
            return self.async_abort(reason="not_lumeair")
        await self.async_set_unique_id(device_id.upper())
        port = discovery_info.port or 80
        # Already added: follow it to its new address.
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info.host, CONF_PORT: port}
        )
        self._host = discovery_info.host
        self._port = port
        self._name = discovery_info.properties.get("name") or device_id
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_pair()

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the discovered sensor's pair code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._host is not None
            code = decode_pair_code(user_input[CONF_PAIR_CODE])
            if code is None:
                errors["base"] = "invalid_code"
            elif code.device_id and code.device_id.upper() != self.unique_id:
                errors["base"] = "wrong_sensor"
            elif await self._check(self._host, self._port, code, errors):
                return self.async_create_entry(
                    title=code.name or self._name or "LumeAir",
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_TOKEN: code.token,
                        CONF_DEVICE_ID: self.unique_id,
                    },
                )
        return self.async_show_form(
            step_id="pair",
            data_schema=PAIR_SCHEMA,
            errors=errors,
            description_placeholders={"name": self._name or ""},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a sensor by its pair code alone (it carries the address)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            code = decode_pair_code(user_input[CONF_PAIR_CODE])
            if code is None:
                errors["base"] = "invalid_code"
            elif device_id := await self._check(code.host, code.port, code, errors):
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured(
                    updates={
                        CONF_HOST: code.host,
                        CONF_PORT: code.port,
                        CONF_TOKEN: code.token,
                    }
                )
                return self.async_create_entry(
                    title=code.name or device_id,
                    data={
                        CONF_HOST: code.host,
                        CONF_PORT: code.port,
                        CONF_TOKEN: code.token,
                        CONF_DEVICE_ID: device_id,
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=PAIR_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """The sensor refused its key, e.g. after it was set up again."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new pair code for the same sensor."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            code = decode_pair_code(user_input[CONF_PAIR_CODE])
            if code is None:
                errors["base"] = "invalid_code"
            elif (
                code.device_id and code.device_id.upper() != entry.data[CONF_DEVICE_ID]
            ):
                errors["base"] = "wrong_sensor"
            elif await self._check(
                entry.data[CONF_HOST], entry.data[CONF_PORT], code, errors
            ):
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: code.token}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=PAIR_SCHEMA,
            errors=errors,
            description_placeholders={"name": entry.title},
        )
