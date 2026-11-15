"""Revision rules: base revision checks, new revision stamps and the undo source.

A revision is never rewritten. Every change, confirmation and undo becomes the
next revision on top of the head, so earlier files keep their bytes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ports import AppError, ProjectStore
from app.schemas.video import CreatedBy, Video

META_FIELDS = frozenset(
    {"revision", "parent_revision", "created_at", "created_by", "change_id"}
)
"""Fields that describe how a revision was made, not what the video is."""


def now() -> datetime:
    return datetime.now(UTC)


def require_head(head: Video, base_revision: int) -> None:
    """Refuse a request made against an older revision. The server never merges."""
    if base_revision != head.revision:
        raise AppError("revision_conflict", detail={"current_revision": head.revision})


def content(video: Video) -> dict[str, object]:
    """The video without its revision metadata."""
    return video.model_dump(mode="json", by_alias=True, exclude=set(META_FIELDS))


def next_revision(
    video: Video, head: Video, created_by: CreatedBy, change_id: str | None = None
) -> Video:
    """Stamp ``video`` as the revision after ``head``."""
    return video.model_copy(
        update={
            "revision": head.revision + 1,
            "parent_revision": head.revision,
            "created_at": now(),
            "created_by": created_by,
            "change_id": change_id,
        }
    )


def undo_source(projects: ProjectStore, head: Video) -> Video:
    """The revision an undo restores: the one right before the head.

    Undo is one step: undoing an undo would redo, so it is refused like an
    undo of the first revision.
    """
    if head.revision == 1 or head.created_by is CreatedBy.undo:
        raise AppError("nothing_to_undo")
    return projects.get_video(head.id, head.revision - 1)


__all__ = ["META_FIELDS", "content", "next_revision", "now", "require_head", "undo_source"]
