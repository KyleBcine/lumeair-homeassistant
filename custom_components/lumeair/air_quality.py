"""The overall air-quality rating, the same way the LumeAir app rates it.

Ported from the app's lib/sensor/air_quality.dart. A reading is rated by
the worst of CO2, PM2.5, PM10 and VOC; comfort readings (temperature,
humidity) don't count.
"""

from __future__ import annotations

from typing import Any

# The ratings, best to worst; also the entity's options.
RATINGS = ["good", "moderate", "poor", "unhealthy", "very_unhealthy", "hazardous"]

_INF = float("inf")

# (below, rating index) per metric: a value is in the first band it's below.
# Particulates use the US EPA AQI breakpoints (PM2.5 as revised in 2024).
_BANDS: dict[str, list[tuple[float, int]]] = {
    "co2": [(800, 0), (1200, 1), (2000, 2), (_INF, 3)],
    "pm2_5": [(9.1, 0), (35.5, 1), (55.5, 2), (125.5, 3), (225.5, 4), (_INF, 5)],
    "pm10": [(55, 0), (155, 1), (255, 2), (355, 3), (425, 4), (_INF, 5)],
    "voc": [(120, 0), (200, 1), (300, 2), (_INF, 3)],
}


def pollutant_value(latest: dict[str, Any], key: str) -> int | float | None:
    """The reading for key, as the sensor reports it, or None when it has
    none yet.

    The sensor reports CO2 and the VOC index as 0 until its first
    measurement; neither is ever really 0 indoors.
    """
    value = latest.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if key in ("co2", "voc") and value <= 0:
        return None
    return value


def air_quality(latest: dict[str, Any]) -> str | None:
    """The worst pollutant's rating; None when no pollutant is reported."""
    worst: int | None = None
    for key, bands in _BANDS.items():
        value = pollutant_value(latest, key)
        if value is None:
            continue
        rating = next(index for below, index in bands if value < below)
        if worst is None or rating > worst:
            worst = rating
    return None if worst is None else RATINGS[worst]
