"""Durable server-only storage for the validated job input.

The public Job response never carries this payload. The runner reads it back
after a restart or a retry; a missing record is reported as None.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from app.ports import AppSettings
from app.schemas.common import TYPEID_PATTERN

JOB_ID = re.compile(TYPEID_PATTERN)


class LocalJobInputStore:
    """One JSON file per job under DATA_DIR/j, published with an atomic rename."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, job_id: str) -> Path:
        if not JOB_ID.fullmatch(job_id):
            raise ValueError(f"invalid job id: {job_id!r}")
        return self.root / f"{job_id}.json"

    def save(self, job_id: str, payload: Mapping[str, Any]) -> None:
        path = self._path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def load(self, job_id: str) -> dict[str, Any] | None:
        path = self._path(job_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"job input for {job_id} is not an object")
        return payload


def create_job_input_store(settings: AppSettings) -> LocalJobInputStore:
    return LocalJobInputStore(settings.data_dir / "j")


__all__ = ["LocalJobInputStore", "create_job_input_store"]
