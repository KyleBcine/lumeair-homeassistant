"""The LumeAir app's pair code: a sensor's address and access key.

The app shows it under Settings > Home Assistant (and Share pair code). It's
unpadded base64url of JSON: {"v": 1, "endpoint": "http://<ip>/metrics.json",
"token": "<access key>", "id": "<device id>", "name": "<room>"}.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PairCode:
    """A decoded pair code."""

    host: str
    port: int
    token: str
    device_id: str | None
    name: str | None


def decode_pair_code(raw: str) -> PairCode | None:
    """Decode a pair code as the app does; None when it isn't one."""
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return None
    padded = compact + "=" * (-len(compact) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    endpoint = data.get("endpoint")
    token = data.get("token")
    if not isinstance(endpoint, str) or not isinstance(token, str):
        return None
    token = token.strip()
    url = urlsplit(endpoint)
    if not token or url.scheme not in ("http", "https") or not url.hostname:
        return None
    try:
        port = url.port or (443 if url.scheme == "https" else 80)
    except ValueError:
        return None

    def text(key: str) -> str | None:
        value = data.get(key)
        return value.strip() or None if isinstance(value, str) else None

    return PairCode(
        host=url.hostname,
        port=port,
        token=token,
        device_id=text("id"),
        name=text("name"),
    )
