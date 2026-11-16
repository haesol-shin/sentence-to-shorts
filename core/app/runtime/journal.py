"""The install journal: `installed.json` below the runtime root.

One record per prepared item: `install_path`, `file`, `sha256`, `bytes`, `version` and
`revision`. The sandbox and the runtime status read the same file. A record is written
only after the files of the item are in place, so a missing or stale record means the
item must be prepared again.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.runtime.fsutil import fsync_dir, raise_disk_full

JOURNAL_NAME = "installed.json"


def journal_path(root: Path) -> Path:
    return root / JOURNAL_NAME


def read(root: Path) -> dict[str, dict[str, Any]]:
    """The journal records; an unreadable journal counts as empty."""
    try:
        payload = json.loads(journal_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if isinstance(value, dict)}


def write(root: Path, records: dict[str, dict[str, Any]]) -> None:
    """Replace the journal in one atomic rename."""
    path = journal_path(root)
    scratch = path.with_name(path.name + ".tmp")
    text = json.dumps(records, indent=2, sort_keys=True) + "\n"
    try:
        with scratch.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(scratch, path)
    except OSError as error:
        scratch.unlink(missing_ok=True)
        raise_disk_full(error)
        raise
    fsync_dir(root)
