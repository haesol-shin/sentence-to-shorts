"""Disk cache of validated sandbox results.

Only output that passed the parent validators is stored. An entry is a folder
named by the cache key with one file per output and an index of names, media
types, SHA-256 digests and the measured meta. A read checks every digest; any
mismatch or read error is a miss, so a damaged entry is run again and the new
result replaces it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from app.ports import ValidatedOutput

KEY = re.compile(r"^[0-9a-f]{64}$")
INDEX = "index.json"


class ResultCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _entry(self, key: str) -> Path:
        if not KEY.match(key):
            raise ValueError("cache key must be a SHA-256 hex digest")
        return self._root / key[:2] / key

    def get(self, key: str) -> ValidatedOutput | None:
        entry = self._entry(key)
        try:
            index = json.loads((entry / INDEX).read_text(encoding="utf-8"))
            files: dict[str, bytes] = {}
            for position, item in enumerate(index["files"]):
                name = item["name"]
                data = (entry / f"{position}.bin").read_bytes()
                if hashlib.sha256(data).hexdigest() != item["sha256"]:
                    return None
                files[name] = data
            meta = index["meta"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not isinstance(meta, dict):
            return None
        return ValidatedOutput(files=files, meta=meta)

    def put(self, key: str, output: ValidatedOutput) -> None:
        """Store an entry atomically; keep a valid entry, replace a damaged one."""
        entry = self._entry(key)
        if entry.exists() and self.get(key) is not None:
            return
        entry.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".put-", dir=entry.parent))
        try:
            items = []
            for position, (name, data) in enumerate(output.files.items()):
                (staging / f"{position}.bin").write_bytes(data)
                items.append({"name": name, "sha256": hashlib.sha256(data).hexdigest()})
            index = {"files": items, "meta": output.meta}
            (staging / INDEX).write_text(json.dumps(index, sort_keys=True), encoding="utf-8")
            if entry.exists():
                # Move the damaged entry aside first, so readers see either the
                # old folder, no folder (a miss) or the complete new one.
                retired = Path(tempfile.mkdtemp(prefix=".old-", dir=entry.parent))
                try:
                    os.replace(entry, retired / "entry")
                except OSError:
                    shutil.rmtree(retired, ignore_errors=True)
                    raise
                shutil.rmtree(retired, ignore_errors=True)
            try:
                os.replace(staging, entry)
            except OSError:
                if not entry.exists():
                    raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
