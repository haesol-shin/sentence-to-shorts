"""Drop the typing cues the old builtin ids created and move the document to v2.

The migration reads no registry: it knows only the two builtin typing ids, so a
document that points at a user typing package keeps its cue for the semantic
check ``typing_cue`` to reject when that document is used.
"""

from __future__ import annotations

import copy
from typing import Any

BUILTIN_TYPING_IDS = frozenset({"typing_keys", "typing_fast"})
"""Builtin ids whose old ``SfxCue`` becomes a caption setting."""

TARGET_VERSION = 2
"""Version of the documents that can hold an ``SfxCue``."""


def _is_builtin_typing_cue(cue: Any) -> bool:
    if not isinstance(cue, dict):
        return False
    ref = cue.get("sfx_id")
    if isinstance(ref, dict):
        return ref.get("id") in BUILTIN_TYPING_IDS
    return isinstance(ref, str) and ref in BUILTIN_TYPING_IDS


def _drop_typing_cues(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "sfx" and isinstance(child, list):
                value[key] = [cue for cue in child if not _is_builtin_typing_cue(cue)]
            else:
                _drop_typing_cues(child)
    elif isinstance(value, list):
        for child in value:
            _drop_typing_cues(child)


def is_cue_document(doc: dict[str, Any]) -> bool:
    """A video or a change plan: the stored documents that can hold an ``SfxCue``."""
    return ("scene_order" in doc and "scenes" in doc) or (
        "ops" in doc and "base_revision" in doc
    )


def migrate(doc: dict[str, Any]) -> dict[str, Any]:
    migrated = copy.deepcopy(doc)
    if not is_cue_document(migrated):
        return migrated
    _drop_typing_cues(migrated)
    migrated["schema_version"] = TARGET_VERSION
    return migrated


__all__ = ["BUILTIN_TYPING_IDS", "TARGET_VERSION", "is_cue_document", "migrate"]
