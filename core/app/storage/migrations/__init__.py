"""Migrations of stored documents and of state.db.

Documents: `v<N>_to_v<N+1>.py` holds a pure `migrate(doc: dict) -> dict` and is
listed in DOCUMENT_MIGRATIONS under N. They apply on read, in order; the stored
file is not rewritten. Version 1 is the first version. Version 2 belongs to the
documents that can hold an `SfxCue` (video, change); project and preset stay at 1
because the new optional caption field does not invalidate them.

state.db: version 1 and the registry are in `app.storage.sqlite`. A later version
adds `db_v<N>.sql` to this folder.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ports import AppError
from app.storage.migrations.v1_to_v2 import migrate as migrate_v1_to_v2

PROJECT_DOCUMENT_VERSION = 1
PRESET_DOCUMENT_VERSION = 1
VIDEO_DOCUMENT_VERSION = 2
CHANGE_DOCUMENT_VERSION = 2
DOCUMENT_VERSION = max(VIDEO_DOCUMENT_VERSION, CHANGE_DOCUMENT_VERSION)

DOCUMENT_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: migrate_v1_to_v2,
}


def upgrade_document(
    doc: dict[str, Any], target: int = DOCUMENT_VERSION
) -> dict[str, Any]:
    """Bring a stored document to ``target``. A newer document is refused."""
    found = doc.get("schema_version")
    if not isinstance(found, int) or isinstance(found, bool) or found < 1:
        raise ValueError("stored document has no valid schema_version")
    if found > target:
        raise AppError(
            "unsupported_version", detail={"found": found, "supported": target}
        )
    for version in range(found, target):
        doc = DOCUMENT_MIGRATIONS[version](doc)
    return doc


__all__ = [
    "CHANGE_DOCUMENT_VERSION",
    "DOCUMENT_MIGRATIONS",
    "DOCUMENT_VERSION",
    "PRESET_DOCUMENT_VERSION",
    "PROJECT_DOCUMENT_VERSION",
    "VIDEO_DOCUMENT_VERSION",
    "upgrade_document",
]
