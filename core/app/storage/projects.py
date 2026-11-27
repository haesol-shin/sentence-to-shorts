"""ProjectStore on state.db and JSON files.

project.json is replaced atomically on every put. Video revisions are immutable:
`p/<project_id>/v/<video_id>/r/<revision>.json` is written once, under the write
transaction that moves the head, and never again. Changes, presets and activity
live in state.db only.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.ports import AppError
from app.schemas.api import ActivityKind, ActivitySpan, Metrics
from app.schemas.change import ChangePlan
from app.schemas.job import Job
from app.schemas.preset import Preset
from app.schemas.project import Project
from app.schemas.video import RevisionInfo, Video
from app.storage.migrations import (
    CHANGE_DOCUMENT_VERSION,
    PRESET_DOCUMENT_VERSION,
    PROJECT_DOCUMENT_VERSION,
    VIDEO_DOCUMENT_VERSION,
    upgrade_document,
)
from app.storage.paths import Layout, write_atomic
from app.storage.sqlite import Database

_PREFIX = re.compile(r"^[a-z]{1,2}$")
_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


class RevisionConflict(AppError):
    """The appended revision is not head + 1."""

    def __init__(self, current_revision: int | None) -> None:
        detail = {} if current_revision is None else {"current_revision": current_revision}
        super().__init__("revision_conflict", detail=detail)
        self.current_revision = current_revision


def new_typeid(prefix: str) -> str:
    """TypeID: prefix, underscore, UUIDv7 bits in lower case Crockford base32."""
    if not _PREFIX.fullmatch(prefix):
        raise ValueError(f"invalid id prefix: {prefix!r}")
    timestamp_ms = time.time_ns() // 1_000_000
    random_bits = secrets.randbits(74)
    raw = bytearray(timestamp_ms.to_bytes(6, "big"))
    raw += (0x7000 | (random_bits >> 62)).to_bytes(2, "big")
    raw += (0x8000_0000_0000_0000 | (random_bits & ((1 << 62) - 1))).to_bytes(8, "big")
    value = int.from_bytes(raw, "big")
    encoded = "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))
    return f"{prefix}_{encoded}"


def utc_text(value: datetime) -> str:
    """Sortable timestamp text for index columns."""
    return value.astimezone(UTC).isoformat()


def _not_found() -> AppError:
    return AppError("not_found")


def _encode(model: BaseModel) -> bytes:
    return model.model_dump_json().encode("utf-8")


def _exists(conn: sqlite3.Connection, table: str, row_id: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)).fetchone() is not None


class SqliteProjectStore:
    def __init__(self, db: Database, layout: Layout) -> None:
        self._db = db
        self._layout = layout

    def new_id(self, prefix: str) -> str:
        return new_typeid(prefix)

    def put_project(self, project: Project) -> None:
        target = self._layout.project_file(project.id)
        with self._db.write() as conn:
            conn.execute(
                "INSERT INTO projects (id, owner_id, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET owner_id = excluded.owner_id",
                (project.id, project.owner_id, utc_text(project.created_at)),
            )
            write_atomic(target, _encode(project))

    def get_project(self, project_id: str) -> Project:
        with self._db.read() as conn:
            if not _exists(conn, "projects", project_id):
                raise _not_found()
        return self._load_project(project_id)

    def list_projects(self, owner_id: str) -> list[Project]:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT id FROM projects WHERE owner_id = ? ORDER BY created_at, id", (owner_id,)
            ).fetchall()
        return [self._load_project(row[0]) for row in rows]

    def _load_project(self, project_id: str) -> Project:
        doc = self._load(self._layout.project_file(project_id))
        return Project.model_validate(upgrade_document(doc, PROJECT_DOCUMENT_VERSION))

    def delete_project(self, project_id: str) -> None:
        """Remove the index rows first, then the files. A crash or a file error in
        between leaves unindexed files, never an index row pointing at a missing file.
        A file error is raised; deleting again removes what is left."""
        project_dir = self._layout.project_dir(project_id)
        with self._db.write() as conn:
            indexed = _exists(conn, "projects", project_id)
            if not indexed and not project_dir.exists():
                raise _not_found()
            video_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM videos WHERE project_id = ?", (project_id,)
                )
            ]
            preset_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM presets WHERE project_id = ?", (project_id,)
                )
            ]
            for video_id in video_ids:
                prefix = f"rev:{video_id}:"
                conn.execute(
                    "DELETE FROM holds WHERE substr(holder, 1, ?) = ? OR holder = ?",
                    (len(prefix), prefix, f"undo:{video_id}"),
                )
            conn.executemany(
                "DELETE FROM holds WHERE holder = ?",
                [(f"preset:{preset_id}",) for preset_id in preset_ids],
            )
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._remove_project_files(project_dir)

    def _remove_project_files(self, project_dir: Path) -> None:
        """Outputs first: their video ids are read from the revision folders, which
        go last with the project folder."""
        videos_dir = project_dir / "v"
        if videos_dir.is_dir():
            for child in videos_dir.iterdir():
                output_dir = self._layout.output_dir(child.name)
                if output_dir.exists():
                    shutil.rmtree(output_dir)
        if project_dir.exists():
            shutil.rmtree(project_dir)

    def append_revision(self, video: Video) -> Video:
        target = self._layout.revision_file(video.project_id, video.id, video.revision)
        with self._db.write() as conn:
            if not _exists(conn, "projects", video.project_id):
                raise _not_found()
            row = conn.execute(
                "SELECT project_id, head FROM videos WHERE id = ?", (video.id,)
            ).fetchone()
            if row is not None and row[0] != video.project_id:
                raise ValueError("a video cannot move to another project")
            head = None if row is None else int(row[1])
            if video.revision != (head or 0) + 1:
                raise RevisionConflict(head)
            # head + 1 has no index row, so this never replaces a committed revision.
            write_atomic(target, _encode(video))
            conn.execute(
                "INSERT INTO videos (id, project_id, head) VALUES (?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET head = excluded.head",
                (video.id, video.project_id, video.revision),
            )
            conn.execute(
                "INSERT INTO revisions (video_id, revision, created_at, created_by, change_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    video.id,
                    video.revision,
                    utc_text(video.created_at),
                    video.created_by.value,
                    video.change_id,
                ),
            )
            if row is None:
                # Read membership only after acquiring the database write lock:
                # another creator may have read the same project defaults.
                project = self._load_project(video.project_id)
                if video.id not in project.video_ids:
                    updated = project.model_copy(
                        update={
                            "video_ids": [*project.video_ids, video.id],
                            "updated_at": max(project.updated_at, video.created_at),
                        }
                    )
                    write_atomic(self._layout.project_file(project.id), _encode(updated))
        return video

    def get_video(self, video_id: str, revision: int | None = None) -> Video:
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT project_id, head FROM videos WHERE id = ?", (video_id,)
            ).fetchone()
        if row is None:
            raise _not_found()
        project_id, head = row[0], int(row[1])
        wanted = head if revision is None else revision
        if not 1 <= wanted <= head:
            raise _not_found()
        doc = self._load(self._layout.revision_file(project_id, video_id, wanted))
        return Video.model_validate(upgrade_document(doc, VIDEO_DOCUMENT_VERSION))

    def list_revisions(self, video_id: str) -> list[RevisionInfo]:
        with self._db.read() as conn:
            if not _exists(conn, "videos", video_id):
                raise _not_found()
            rows = conn.execute(
                "SELECT revision, created_at, created_by, change_id FROM revisions "
                "WHERE video_id = ? ORDER BY revision",
                (video_id,),
            ).fetchall()
        return [
            RevisionInfo(
                revision=row[0],
                created_at=datetime.fromisoformat(row[1]),
                created_by=row[2],
                change_id=row[3],
            )
            for row in rows
        ]

    def put_change(self, plan: ChangePlan) -> None:
        with self._db.write() as conn:
            if not _exists(conn, "videos", plan.video_id):
                raise _not_found()
            conn.execute(
                "INSERT INTO changes (id, video_id, doc) VALUES (?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET doc = excluded.doc "
                "WHERE changes.video_id = excluded.video_id",
                (plan.id, plan.video_id, plan.model_dump_json()),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("a change cannot move to another video")

    def get_change(self, change_id: str) -> ChangePlan:
        with self._db.read() as conn:
            row = conn.execute("SELECT doc FROM changes WHERE id = ?", (change_id,)).fetchone()
        if row is None:
            raise _not_found()
        return ChangePlan.model_validate(
            upgrade_document(json.loads(row[0]), CHANGE_DOCUMENT_VERSION)
        )

    def list_changes(self, video_id: str) -> list[ChangePlan]:
        with self._db.read() as conn:
            if not _exists(conn, "videos", video_id):
                raise _not_found()
            rows = conn.execute(
                "SELECT doc FROM changes WHERE video_id = ? ORDER BY id", (video_id,)
            ).fetchall()
        return [
            ChangePlan.model_validate(
                upgrade_document(json.loads(row[0]), CHANGE_DOCUMENT_VERSION)
            )
            for row in rows
        ]

    def put_preset(self, preset: Preset) -> None:
        with self._db.write() as conn:
            if not _exists(conn, "projects", preset.project_id):
                raise _not_found()
            conn.execute(
                "INSERT INTO presets (id, project_id, created_at, doc) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET doc = excluded.doc "
                "WHERE presets.project_id = excluded.project_id",
                (
                    preset.id,
                    preset.project_id,
                    utc_text(preset.created_at),
                    preset.model_dump_json(),
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("a preset cannot move to another project")

    def list_presets(self, project_id: str) -> list[Preset]:
        with self._db.read() as conn:
            if not _exists(conn, "projects", project_id):
                raise _not_found()
            rows = conn.execute(
                "SELECT doc FROM presets WHERE project_id = ? ORDER BY created_at, id",
                (project_id,),
            ).fetchall()
        return [
            Preset.model_validate(
                upgrade_document(json.loads(row[0]), PRESET_DOCUMENT_VERSION)
            )
            for row in rows
        ]

    def add_activity(self, video_id: str, spans: list[ActivitySpan]) -> None:
        with self._db.write() as conn:
            if not _exists(conn, "videos", video_id):
                raise _not_found()
            conn.executemany(
                "INSERT INTO activity (video_id, kind, start_ms, end_ms) VALUES (?, ?, ?, ?)",
                [(video_id, span.kind.value, span.start_ms, span.end_ms) for span in spans],
            )

    def metrics(self, video_id: str) -> Metrics:
        """Activity totals, plus job wall time, tokens and rebuilt scenes of the video.

        Tokens sum the usage ledger, which holds failed and retried requests too; a
        token count no request reported stays null. Wall time sums the finished jobs'
        start to end, and rebuilt scenes are the ids the jobs' stage records list.
        """
        with self._db.read() as conn:
            if not _exists(conn, "videos", video_id):
                raise _not_found()
            totals = dict(
                conn.execute(
                    "SELECT kind, SUM(MAX(end_ms - start_ms, 0)) FROM activity "
                    "WHERE video_id = ? GROUP BY kind",
                    (video_id,),
                ).fetchall()
            )
            tokens = conn.execute(
                "SELECT SUM(CASE WHEN COALESCE(e.input_tokens, e.cache_read_tokens, "
                "e.cache_write_tokens) IS NOT NULL THEN COALESCE(e.input_tokens, 0) "
                "+ COALESCE(e.cache_read_tokens, 0) + COALESCE(e.cache_write_tokens, 0) "
                "END), SUM(e.output_tokens) "
                "FROM usage_events e JOIN jobs j ON j.id = e.job_id "
                "WHERE j.video_id = ?",
                (video_id,),
            ).fetchone()
            documents = conn.execute(
                "SELECT doc FROM jobs WHERE video_id = ? ORDER BY created_at, id", (video_id,)
            ).fetchall()
        wall_ms = 0
        rebuilt: list[str] = []
        for (document,) in documents:
            job = Job.model_validate_json(document)
            if job.started_at is not None and job.ended_at is not None:
                wall_ms += max(0, int((job.ended_at - job.started_at).total_seconds() * 1000))
            for record in job.stages:
                rebuilt.extend(
                    scene_id for scene_id in record.rebuilt_scene_ids if scene_id not in rebuilt
                )
        return Metrics(
            active_ms=int(totals.get(ActivityKind.active.value) or 0),
            waiting_ms=int(totals.get(ActivityKind.waiting.value) or 0),
            job_wall_ms=wall_ms,
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            cost_micro_usd=None,
            regenerated_scene_ids=rebuilt,
        )

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        try:
            doc = json.loads(path.read_bytes())
        except FileNotFoundError:
            raise _not_found() from None
        if not isinstance(doc, dict):
            raise ValueError("stored document is not an object")
        return doc


__all__ = ["RevisionConflict", "SqliteProjectStore", "new_typeid", "utc_text"]
