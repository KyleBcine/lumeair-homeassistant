"""The pair code and the air-quality rating, which mirror the app."""

from __future__ import annotations

import pytest

from custom_components.lumeair.air_quality import air_quality
from custom_components.lumeair.pair_code import decode_pair_code

from .conftest import DEVICE_ID, HOST, TOKEN, pair_code


def test_pair_code_round_trip() -> None:
    """A code from the app decodes to the sensor's address and key."""
    code = decode_pair_code(pair_code())
    assert code is not None
    assert (code.host, code.port, code.token) == (HOST, 80, TOKEN)
    assert (code.device_id, code.name) == (DEVICE_ID, "Bedroom")

    # Pasted with spaces and line breaks, as messaging apps wrap it.
    raw = pair_code(name=None)
    wrapped = f" {raw[:20]}\n{raw[20:]} "
    code = decode_pair_code(wrapped)
    assert code is not None and code.name is None


@pytest.mark.parametrize(
    "raw",
    ["", "not a code", "e30", pair_code(token=" "), "eyJ2IjoyfQ"],
)
def test_bad_pair_codes(raw: str) -> None:
    """Empty, garbage, {}, a blank key and an unknown version are refused."""
    assert decode_pair_code(raw) is None


@pytest.mark.parametrize(
    ("readings", "expected"),
    [
        ({"co2": 640, "pm2_5": 5, "voc": 101}, "good"),
        ({"co2": 799}, "good"),
        ({"co2": 800}, "moderate"),
        ({"co2": 1200}, "poor"),
        ({"co2": 2000}, "unhealthy"),
        ({"pm2_5": 9}, "good"),
        ({"pm2_5": 9.1}, "moderate"),
        ({"pm2_5": 55.5}, "unhealthy"),
        ({"pm2_5": 300}, "hazardous"),
        ({"pm10": 54}, "good"),
        ({"pm10": 254}, "poor"),
        ({"pm10": 424}, "very_unhealthy"),
        ({"voc": 119}, "good"),
        ({"voc": 120}, "moderate"),
        ({"voc": 350}, "unhealthy"),
        # The worst pollutant wins; comfort readings don't count.
        ({"co2": 640, "pm2_5": 40, "temp": 35}, "poor"),
        # 0 means "not measured yet" for CO2 and VOC; PM null means stale.
        ({"co2": 0, "voc": 0, "pm2_5": None}, None),
        ({}, None),
    ],
)
def test_air_quality_matches_the_app(
    readings: dict[str, float | None], expected: str | None
) -> None:
    """The same bands as the app's lib/sensor/air_quality.dart."""
    assert air_quality(readings) == expected
