"""Canonical JSON helpers are defined once in app.ports."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.ports import canonical_json

API_VERSION = 1
SPEED_DECIMALS = 2


def speed_key(speed: float) -> str:
    """TTS cache key form of a speed ratio: two decimals, for example "1.00"."""
    if round(speed, SPEED_DECIMALS) != speed:
        raise ValueError("speed is a ratio with at most two decimals")
    return f"{speed:.{SPEED_DECIMALS}f}"


def cache_key(kind: str, inputs: Mapping[str, Any], *, api_version: int = API_VERSION) -> str:
    payload = {"api_version": api_version, "inputs": inputs, "kind": kind}
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


__all__ = ["API_VERSION", "cache_key", "digest_bytes", "digest_file", "speed_key"]
