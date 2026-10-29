"""Diagnostics download, without the access key or addresses."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_TOKEN
from homeassistant.core import HomeAssistant

from .coordinator import LumeAirConfigEntry

TO_REDACT = {CONF_TOKEN, CONF_HOST, "ip"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LumeAirConfigEntry
) -> dict[str, Any]:
    """The entry and the last poll, redacted."""
    data = entry.runtime_data.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "data": async_redact_data(
            {
                **asdict(data),
                "active_alerts": None
                if data.active_alerts is None
                else sorted(data.active_alerts),
            },
            TO_REDACT,
        ),
    }
