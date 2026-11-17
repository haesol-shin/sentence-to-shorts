"""ArtifactStore: files under CACHE_DIR/a, rows in state.db.

publish measures the bytes and the SHA-256 of the staged file, renames it into
`a/<2 hex>/<artifact_id>.<ext>`, hashes the published file again and indexes it only
when both agree. find re-checks existence and digest, so a damaged file is never
reused. sweep removes cache artifacts that no holder references, index row first.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.ports import AppError
from app.schemas.artifact import Artifact, ArtifactKind, ArtifactRoot, MediaMeta
from app.schemas.common import DIGEST_PATTERN, TYPEID_PATTERN
from app.storage.paths import Layout, check_id, copy_atomic, file_digest, fsync_dir
from app.storage.projects import new_typeid, utc_text
from app.storage.sqlite import Database

log = logging.getLogger(__name__)

EXTENSIONS: dict[ArtifactKind, str] = {
    ArtifactKind.still_png: "png",
    ArtifactKind.part_png: "png",
    ArtifactKind.layer_png: "png",
    ArtifactKind.tts_wav: "wav",
    ArtifactKind.timing_json: "json",
    ArtifactKind.clip_mp4: "mp4",
    ArtifactKind.mix_wav: "wav",
    ArtifactKind.final_mp4: "mp4",
    ArtifactKind.srt: "srt",
    ArtifactKind.bgm_wav: "wav",
    ArtifactKind.ref_frame_png: "png",
    ArtifactKind.ref_audio_wav: "wav",
}
DOWNLOAD_KINDS: dict[str, ArtifactKind] = {
    "mp4": ArtifactKind.final_mp4,
    "srt": ArtifactKind.srt,
}

_ID = TYPEID_PATTERN[1:-1]
_HOLDER = re.compile(
    rf"^(rev:{_ID}:[1-9][0-9]*|undo:{_ID}|style:[0-9a-f]{{16,64}}|preset:{_ID})$"
)
_DIGEST = re.compile(DIGEST_PATTERN)
_OWNER = re.compile(r"^[a-z0-9_-]{1,32}$")
_MEDIA = TypeAdapter(MediaMeta)
_COLUMNS = (
    "id, kind, owner_id, digest, bytes, cache_key, root, path, created_at, job_id, media"
)


class ArtifactRejected(ValueError):
    """The staged file failed verification and was not published."""


def _row_artifact(row: tuple[Any, ...]) -> Artifact:
    return Artifact(
        id=row[0],
        kind=row[1],
        owner_id=row[2],
        digest=row[3],
        bytes=row[4],
        cache_key=row[5],
        root=row[6],
        path=row[7],
        created_at=datetime.fromisoformat(row[8]),
        job_id=row[9],
        media=json.loads(row[10]),
    )


def _check_holder(holder: str) -> str:
    if not _HOLDER.fullmatch(holder):
        raise ValueError(f"invalid holder: {holder!r}")
    return holder


def _check_owner(owner_id: str) -> str:
    if not _OWNER.fullmatch(owner_id):
        raise ValueError(f"invalid owner id: {owner_id!r}")
    return owner_id


class FileArtifactStore:
    def __init__(self, db: Database, layout: Layout) -> None:
        self._db = db
        self._layout = layout

    def _absolute(self, artifact: Artifact) -> Path:
        root = self._layout.data if artifact.root is ArtifactRoot.data else self._layout.cache
        return root / artifact.path

    def _intact(self, artifact: Artifact) -> bool:
        path = self._absolute(artifact)
        if path.is_symlink() or not path.is_file():
            return False
        return file_digest(path) == (artifact.digest, artifact.bytes)

    def find(self, owner_id: str, cache_key: str) -> Artifact | None:
        """Newest indexed artifact for the owner's key whose file matches its digest."""
        _check_owner(owner_id)
        with self._db.read() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM artifacts WHERE owner_id = ? AND cache_key = ? "
                "ORDER BY created_at DESC, id DESC",
                (owner_id, cache_key),
            ).fetchall()
        for row in rows:
            artifact = _row_artifact(row)
            if self._intact(artifact):
                return artifact
        return None

    def publish(
        self,
        owner_id: str,
        kind: ArtifactKind,
        cache_key: str,
        tmp: Path,
        media: dict[str, Any],
        job_id: str | None,
    ) -> Artifact:
        _check_owner(owner_id)
        kind = ArtifactKind(kind)
        if not _DIGEST.fullmatch(cache_key):
            raise ArtifactRejected("cache key is not a SHA-256 digest")
        if tmp.is_symlink() or not tmp.is_file():
            raise ArtifactRejected("staged artifact is not a regular file")
        digest, size = file_digest(tmp)
        if size == 0:
            raise ArtifactRejected("staged artifact is empty")
        existing = self.find(owner_id, cache_key)
        if existing is not None and existing.digest == digest:
            tmp.unlink()
            return existing
        artifact_id = new_typeid("a")
        artifact = Artifact(
            id=artifact_id,
            kind=kind,
            owner_id=owner_id,
            digest=digest,
            bytes=size,
            cache_key=cache_key,
            root=ArtifactRoot.cache,
            path=Layout.cache_artifact(digest, artifact_id, EXTENSIONS[kind]),
            created_at=datetime.now(UTC),
            job_id=None if job_id is None else check_id(job_id),
            media=_MEDIA.validate_python(media),
        )
        target = self._absolute(artifact)
        _move(tmp, target)
        try:
            if file_digest(target) != (digest, size):
                log.warning(
                    "artifact changed during publish",
                    extra={"event": "artifact_rejected", "job_id": job_id},
                )
                raise ArtifactRejected("artifact changed after verification")
            with self._db.write() as conn:
                conn.execute(
                    f"INSERT INTO artifacts ({_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        artifact.id,
                        artifact.kind.value,
                        artifact.owner_id,
                        artifact.digest,
                        artifact.bytes,
                        artifact.cache_key,
                        artifact.root.value,
                        artifact.path,
                        utc_text(artifact.created_at),
                        artifact.job_id,
                        json.dumps(artifact.media, sort_keys=True),
                    ),
                )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return artifact

    def _get(self, conn: sqlite3.Connection, artifact_id: str) -> Artifact:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise AppError("not_found")
        return _row_artifact(row)

    def get(self, owner_id: str, artifact_id: str) -> Artifact:
        """An artifact id of this owner; another owner's id is `not_found`."""
        with self._db.read() as conn:
            artifact = self._get(conn, artifact_id)
        if artifact.owner_id != owner_id:
            raise AppError("not_found")
        return artifact

    def path(self, artifact_id: str) -> Path:
        with self._db.read() as conn:
            artifact = self._get(conn, artifact_id)
        return self._absolute(artifact)

    def download_path(self, owner_id: str, video_id: str, kind: str) -> Path:
        """The final file held by the newest revision, copied once to DATA_DIR/o/."""
        _check_owner(owner_id)
        artifact_kind = DOWNLOAD_KINDS.get(kind)
        if artifact_kind is None:
            raise AppError("not_found")
        prefix = f"rev:{check_id(video_id)}:"
        with self._db.read() as conn:
            rows = conn.execute(
                f"SELECT h.holder, {', '.join('a.' + c for c in _COLUMNS.split(', '))} "
                "FROM holds h JOIN artifacts a ON a.id = h.artifact_id "
                "WHERE a.owner_id = ? AND a.kind = ? AND substr(h.holder, 1, ?) = ?",
                (owner_id, artifact_kind.value, len(prefix), prefix),
            ).fetchall()
        if not rows:
            raise AppError("not_built")
        newest = max(rows, key=lambda row: int(row[0][len(prefix) :]))
        artifact = _row_artifact(newest[1:])
        target = self._layout.output_file(video_id, artifact.id, EXTENSIONS[artifact_kind])
        if target.is_file() and file_digest(target) == (artifact.digest, artifact.bytes):
            return target
        source = self._absolute(artifact)
        if not self._intact(artifact) or copy_atomic(source, target) != (
            artifact.digest,
            artifact.bytes,
        ):
            target.unlink(missing_ok=True)
            raise AppError("not_built")
        return target

    def job_dir(self, job_id: str) -> Path:
        path = self._layout.job_dir(job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def hold(self, artifact_ids: list[str], holder: str) -> None:
        _check_holder(holder)
        with self._db.write() as conn:
            for artifact_id in artifact_ids:
                self._get(conn, artifact_id)
            conn.executemany(
                "INSERT OR IGNORE INTO holds (holder, artifact_id) VALUES (?, ?)",
                [(holder, artifact_id) for artifact_id in artifact_ids],
            )

    def release(self, holder: str) -> None:
        _check_holder(holder)
        with self._db.write() as conn:
            conn.execute("DELETE FROM holds WHERE holder = ?", (holder,))

    def sweep(self) -> int:
        """Delete unheld cache artifacts. Rows go first, so a crash leaves at most an
        unindexed file and never an index row without its file."""
        with self._db.write() as conn:
            rows = conn.execute(
                "SELECT id, path FROM artifacts WHERE root = 'cache' AND NOT EXISTS "
                "(SELECT 1 FROM holds WHERE holds.artifact_id = artifacts.id)"
            ).fetchall()
            conn.executemany("DELETE FROM artifacts WHERE id = ?", [(row[0],) for row in rows])
        for _, relative in rows:
            (self._layout.cache / relative).unlink(missing_ok=True)
        return len(rows)


def _move(tmp: Path, target: Path) -> None:
    """Atomic rename; a staged file on another volume is copied in through a temp name."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(tmp, target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        copy_atomic(tmp, target)
        tmp.unlink()
        return
    fsync_dir(target.parent)


__all__ = ["DOWNLOAD_KINDS", "EXTENSIONS", "ArtifactRejected", "FileArtifactStore"]
