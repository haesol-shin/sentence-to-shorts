"""The runtime lock lists the pinned Deno and Pyodide files with valid hashes."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.sandbox

LOCK = Path(__file__).resolve().parents[2] / "config" / "runtime.lock.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_runtime_lock_entries_have_valid_hashes_and_urls() -> None:
    document = json.loads(LOCK.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    items = {item["id"]: item for item in document["items"]}
    assert set(items) == {"deno", "pyodide-core", "pyodide-pillow"}

    for item in items.values():
        assert re.fullmatch(r"\d+\.\d+\.\d+", item["version"])
        assert re.fullmatch(r"[0-9a-f]{40}", item["revision"])
        assert item["files"], item["id"]
        seen: set[tuple[str, str]] = set()
        for entry in item["files"]:
            assert entry["url"].startswith("https://")
            assert entry["bytes"] > 0
            assert SHA256.match(entry["sha256"]), entry
            key = (entry["os"], entry["arch"])
            assert key not in seen, f"duplicate runtime file for {key}"
            seen.add(key)

    deno = {(entry["os"], entry["arch"]) for entry in items["deno"]["files"]}
    assert deno == {
        ("windows", "x86_64"),
        ("linux", "x86_64"),
        ("linux", "aarch64"),
    }
    pillow = items["pyodide-pillow"]["files"][0]
    assert pillow["file"].endswith(".whl")
