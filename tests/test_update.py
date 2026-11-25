"""Firmware updates: the release list, and installing from Home Assistant."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.lumeair import update as update_module
from custom_components.lumeair.firmware import (
    RELEASE_PREFIX,
    parse_release,
    version_tuple,
)

from .conftest import LATEST, MANIFEST, mock_sensor

ENTITY = "update.bedroom_firmware"


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real waiting between checks on an install."""
    monkeypatch.setattr(update_module, "POLL_INTERVAL_S", 0)


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def install(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "update", "install", {"entity_id": ENTITY}, blocking=True
    )


def test_release_list_is_read_strictly() -> None:
    release = parse_release(MANIFEST)
    assert release is not None
    assert (release.version, release.url) == ("0.8.0", MANIFEST["url"])
    assert release.notes == MANIFEST["notes"]
    for bad in (
        {"version": "0.8"},
        {"version": "v0.8.0"},
        {"url": "https://example.com/lumeair-0.8.0.bin"},
        {"url": f"{RELEASE_PREFIX}lumeair-0.8.0.bin?x=1"},
        {"url": f"{RELEASE_PREFIX}../lumeair-0.8.0.bin"},
        {"url": f"{RELEASE_PREFIX}manifest.json"},
        {"sha256": "ab" * 31},
        {"sha256": "zz" * 32},
        {"signature": "cd" * 63},
    ):
        assert parse_release({**MANIFEST, **bad}) is None, bad
    assert parse_release(["not", "a", "manifest"]) is None
    assert version_tuple("0.10.2") > version_tuple("0.9.9")
    assert version_tuple("65536.0.0") is None


async def test_a_newer_release_is_offered(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_sensor(aioclient_mock)
    await setup(hass, config_entry)
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == "0.5.0"
    assert state.attributes["latest_version"] == "0.8.0"
    assert state.attributes["release_summary"] == MANIFEST["notes"]


@pytest.mark.parametrize(
    ("latest", "release"),
    [
        # Already on the latest release.
        ({**LATEST, "fw_version": "0.8.0"}, MANIFEST),
        # The earlier board: releases are signed for the SEN66 board only.
        ({k: v for k, v in LATEST.items() if k != "model"}, MANIFEST),
        # The LumeAir website can't be reached: the sensor still loads.
        (LATEST, None),
    ],
)
async def test_nothing_is_offered(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    latest: dict[str, Any],
    release: dict[str, Any] | None,
) -> None:
    mock_sensor(aioclient_mock, latest=latest, release=release)
    await setup(hass, config_entry)
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes["latest_version"] == state.attributes["installed_version"]
    assert hass.states.get("sensor.bedroom_carbon_dioxide").state == "640"


async def test_install_passes_the_release_and_follows_it(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    sensor = mock_sensor(aioclient_mock)
    await setup(hass, config_entry)
    sensor.installs = "0.8.0"
    sensor.ota_states = [
        {"state": "downloading", "progress": 40},
        {"state": "verifying", "progress": 100},
        {"state": "rebooting", "progress": 100},
        {"state": "idle", "progress": 0},
    ]
    progress: list[Any] = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: progress.append(
            event.data["new_state"].attributes.get("update_percentage")
        )
        if event.data["entity_id"] == ENTITY
        else None,
    )

    await install(hass)

    # The sensor got the release exactly as published, in a signed request.
    assert sensor.ota_posts == [
        {
            "version": MANIFEST["version"],
            "url": MANIFEST["url"],
            "sha256": MANIFEST["sha256"],
            "signature": MANIFEST["signature"],
        }
    ]
    assert sensor.plain_keys == 0
    assert 40 in progress
    # Back after the restart (a new boot ID, so the client re-synced its
    # clock), on the new version, with nothing left to offer.
    state = hass.states.get(ENTITY)
    assert state.state == STATE_OFF
    assert state.attributes["installed_version"] == "0.8.0"
    assert state.attributes["in_progress"] is False


@pytest.mark.parametrize(
    ("reply", "key"),
    [
        ((409, {"error": "on_trial"}), "update_refused_on_trial"),
        ((400, {"error": "bad_signature"}), "update_refused_bad_signature"),
        ((409, {"error": "not_newer", "running": "0.8.0"}), "update_refused_not_newer"),
        ((400, {"error": "invalid_url"}), "update_refused"),
        ((404, {}), "update_refused_unsupported"),
    ],
)
async def test_a_refusal_is_explained(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    reply: tuple[int, dict[str, Any]],
    key: str,
) -> None:
    sensor = mock_sensor(aioclient_mock)
    await setup(hass, config_entry)
    sensor.ota_reply = reply
    with pytest.raises(HomeAssistantError) as err:
        await install(hass)
    assert err.value.translation_key == key
    assert hass.states.get(ENTITY).attributes["in_progress"] is False


async def test_a_failed_download_is_explained(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    sensor = mock_sensor(aioclient_mock)
    await setup(hass, config_entry)
    sensor.ota_states = [
        {"state": "downloading", "progress": 10},
        {"state": "failed", "progress": 10, "error": "download_failed"},
    ]
    with pytest.raises(HomeAssistantError) as err:
        await install(hass)
    assert err.value.translation_key == "update_failed"
    assert err.value.translation_placeholders == {"reason": "download_failed"}


async def test_a_sensor_back_on_the_old_version_is_reported(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It restarted, but the new version didn't stay (or didn't install)."""
    monkeypatch.setattr(update_module, "RESTART_TIMEOUT_S", 0.2)
    sensor = mock_sensor(aioclient_mock)
    await setup(hass, config_entry)
    sensor.ota_states = [{"state": "rebooting", "progress": 100}]
    with pytest.raises(HomeAssistantError) as err:
        await install(hass)
    assert err.value.translation_key == "update_not_installed"
    assert hass.states.get(ENTITY).state == STATE_ON
