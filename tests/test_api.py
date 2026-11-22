"""Signed requests: the shared vectors, and never sending the plain key to a
sensor that signs."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.lumeair.api import (
    AUTH_HEADER,
    LEGACY_AUTH_HEADER,
    CannotConnect,
    InvalidAuth,
    LumeAirClient,
    sign,
    signed_text,
)

from .conftest import HOST, LATEST, TOKEN, mock_sensor

# The shared vectors (the firmware's test/test_request_auth and boot
# self-test, and the app's test/sensor_auth_test.dart use the same ones).
VECTOR_KEY = "sJ3k9_Qw-2mZp7Lx0aVbN4cTe8uYhR1D"
VECTOR_BOOT = "0123456789abcdef"
VECTOR_NONCE = "AAECAwQFBgcICQoLDA0ODw"


def test_signed_text_and_signature_match_the_shared_vectors() -> None:
    text = signed_text(
        "GET",
        "/history",
        VECTOR_BOOT,
        4242,
        VECTOR_NONCE,
        [("since", "0"), ("limit", "1200"), ("_t", "1700000000000")],
    )
    assert text == (
        b"lumeair-request-v1\nGET\n/history\n0123456789abcdef\n4242\n"
        b"AAECAwQFBgcICQoLDA0ODw\nq5:since1:0\nq5:limit4:1200\nq2:_t13:1700000000000\n"
    )
    assert sign(VECTOR_KEY, text) == "Z_z1jKtG7Mwhv5hOZ7csF-xP0ioJbrakq0eeQ6lcTmg"
    empty = signed_text("GET", "/latest", VECTOR_BOOT, 7, VECTOR_NONCE, [])
    assert sign(VECTOR_KEY, empty) == "IaFZ9ih-e-GYr5yYaOYHtqJDvFnwdw22UlOkmhnLhtk"


def headers_sent(aioclient_mock: AiohttpClientMocker) -> list[dict[str, str]]:
    return [dict(call[3] or {}) for call in aioclient_mock.mock_calls]


async def test_a_signing_sensor_never_gets_the_plain_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    sensor = mock_sensor(aioclient_mock, active=["co2"])
    client = LumeAirClient(async_get_clientsession(hass), HOST, 80, TOKEN)
    assert (await client.latest())["co2"] == LATEST["co2"]
    assert await client.active_alerts() == frozenset({"co2"})
    assert await client.wifi_rssi() == -58
    assert client.signs
    assert sensor.signed == 3
    assert sensor.plain_keys == 0
    for headers in headers_sent(aioclient_mock):
        assert LEGACY_AUTH_HEADER not in headers
        assert TOKEN not in str(headers)
    # The clock is read once, then reused.
    clock_calls = [c for c in aioclient_mock.mock_calls if c[1].path == "/auth/clock"]
    assert len(clock_calls) == 1


async def test_older_firmware_gets_the_plain_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    sensor = mock_sensor(aioclient_mock, signs=False)
    client = LumeAirClient(async_get_clientsession(hass), HOST, 80, TOKEN)
    assert (await client.latest())["device_id"] == LATEST["device_id"]
    assert sensor.plain_keys == 1
    assert not client.signs
    # Not asked again on every poll.
    await client.latest()
    clock_calls = [c for c in aioclient_mock.mock_calls if c[1].path == "/auth/clock"]
    assert len(clock_calls) == 1


async def test_a_known_signer_is_never_downgraded(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Someone on the network answering "not found" for /auth/clock can't
    make the client send the key."""
    mock_sensor(aioclient_mock, signs=False)
    client = LumeAirClient(async_get_clientsession(hass), HOST, 80, TOKEN, signs=True)
    with pytest.raises(CannotConnect):
        await client.latest()
    assert all(LEGACY_AUTH_HEADER not in h for h in headers_sent(aioclient_mock))


async def test_a_restart_is_followed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    sensor = mock_sensor(aioclient_mock)
    client = LumeAirClient(async_get_clientsession(hass), HOST, 80, TOKEN)
    await client.latest()
    sensor.reboot()
    # Refused as stale once, then signed with the new clock.
    assert (await client.latest())["co2"] == LATEST["co2"]
    assert sensor.signed == 2
    last = headers_sent(aioclient_mock)[-1][AUTH_HEADER]
    assert f"b={sensor.boot}" in last


async def test_a_wrong_key_is_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_sensor(aioclient_mock)
    client = LumeAirClient(async_get_clientsession(hass), HOST, 80, "not-the-key")
    with pytest.raises(InvalidAuth):
        await client.latest()


async def test_signature_covers_the_query(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_sensor(aioclient_mock)
    client = LumeAirClient(async_get_clientsession(hass), HOST, 80, TOKEN)
    await client.active_alerts()
    call = next(c for c in aioclient_mock.mock_calls if c[1].path == "/alerts")
    assert call[1].path == "/alerts"
    assert list(call[1].query.items()) == [("limit", "1")]
