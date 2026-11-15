"""Migrations of stored documents and of state.db.

Documents: `v<N>_to_v<N+1>.py` holds a pure `migrate(doc: dict) -> dict` and is
listed in DOCUMENT_MIGRATIONS under N. They apply on read, in order; the stored
file is not rewritten. Version 1 is the first version, so the table is empty.

state.db: version 1 and the registry are in `app.storage.sqlite`. A later version
adds `db_v<N>.sql` to this folder.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ports import AppError

DOCUMENT_VERSION = 1

DOCUMENT_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def upgrade_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Bring a stored document to DOCUMENT_VERSION. A newer document is refused."""
    found = doc.get("schema_version")
    if not isinstance(found, int) or isinstance(found, bool) or found < 1:
        raise ValueError("stored document has no valid schema_version")
    if found > DOCUMENT_VERSION:
        raise AppError(
            "unsupported_version", detail={"found": found, "supported": DOCUMENT_VERSION}
        )
    for version in range(found, DOCUMENT_VERSION):
        doc = DOCUMENT_MIGRATIONS[version](doc)
    return doc


__all__ = ["DOCUMENT_MIGRATIONS", "DOCUMENT_VERSION", "upgrade_document"]
