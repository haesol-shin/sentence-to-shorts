"""state.db: migrations keep the original on failure, writes stay inside short
transactions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import Job
from app.storage.artifacts import FileArtifactStore
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore
from app.storage.sqlite import (
    Database,
    Migration,
    MigrationFailed,
    registered_migrations,
)
from tests.storage.conftest import next_revision, staged

CACHE_KEY = "c" * 64
WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLACE")
LATEST = registered_migrations()[-1].version


def _rows(path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT id, owner_id FROM projects ORDER BY id").fetchall()
    finally:
        conn.close()


def test_migration_failure_keeps_original_and_backup(layout: Layout, project) -> None:
    database = Database.open(layout.state_db)
    SqliteProjectStore(database, layout).put_project(project)
    database.close()
    before = _rows(layout.state_db)

    broken = Migration(
        LATEST + 1, "ALTER TABLE projects ADD COLUMN note TEXT;\nSELECT * FROM missing;"
    )
    with pytest.raises(MigrationFailed):
        Database.open(layout.state_db, migrations=[*registered_migrations(), broken])

    backup = layout.state_db.with_name(f"state.db.bak-{LATEST}")
    assert backup.is_file()
    assert _rows(backup) == before
    assert _rows(layout.state_db) == before
    conn = sqlite3.connect(layout.state_db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST
        columns = [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
    finally:
        conn.close()
    assert "note" not in columns


def test_migration_applies_pending_versions_in_order(layout: Layout) -> None:
    Database.open(layout.state_db).close()
    added = Migration(LATEST + 1, "ALTER TABLE projects ADD COLUMN note TEXT;")
    database = Database.open(layout.state_db, migrations=[*registered_migrations(), added])
    try:
        assert database.user_version == LATEST + 1
    finally:
        database.close()
    assert layout.state_db.with_name(f"state.db.bak-{LATEST}").is_file()


def test_migration_failure_rolls_back_every_pending_step(layout: Layout, project) -> None:
    database = Database.open(layout.state_db)
    SqliteProjectStore(database, layout).put_project(project)
    database.close()
    before = _rows(layout.state_db)

    steps = [
        *registered_migrations(),
        Migration(LATEST + 1, "DELETE FROM projects;"),
        Migration(LATEST + 2, "SELECT * FROM missing;"),
    ]
    with pytest.raises(MigrationFailed):
        Database.open(layout.state_db, migrations=steps)

    assert _rows(layout.state_db) == before
    conn = sqlite3.connect(layout.state_db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST
    finally:
        conn.close()



def test_migration_refuses_newer_database(layout: Layout) -> None:
    newer = [*registered_migrations(), Migration(LATEST + 1, "")]
    Database.open(layout.state_db, migrations=newer).close()
    with pytest.raises(MigrationFailed):
        Database.open(layout.state_db)


def test_migration_registry_reads_later_files_in_order(tmp_path: Path) -> None:
    (tmp_path / "db_v3.sql").write_text("CREATE TABLE c (x);", encoding="utf-8")
    (tmp_path / "db_v2.sql").write_text("CREATE TABLE b (x);", encoding="utf-8")
    assert [m.version for m in registered_migrations(tmp_path)] == [1, 2, 3]
    (tmp_path / "db_v5.sql").write_text("CREATE TABLE e (x);", encoding="utf-8")
    with pytest.raises(RuntimeError):
        registered_migrations(tmp_path)


def test_short_transaction_rejects_write_outside(db: Database) -> None:
    with db.read() as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO projects (id, owner_id, created_at) VALUES ('x', 'o', 't')")
    with pytest.raises(RuntimeError), db.write() as conn:
        conn.execute("INSERT INTO projects (id, owner_id, created_at) VALUES ('x', 'o', 't')")
        raise RuntimeError("abort")
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


def test_short_transaction_wraps_every_store_write(
    db: Database, layout: Layout, project, video, tmp_path: Path
) -> None:
    statements: list[str] = []
    with db.read() as conn:
        conn.set_trace_callback(statements.append)
    projects = SqliteProjectStore(db, layout)
    artifacts = FileArtifactStore(db, layout)

    projects.put_project(project)
    projects.append_revision(video)
    projects.append_revision(next_revision(video))
    published = artifacts.publish(
        PERSONAL_OWNER_ID, "tts_wav", CACHE_KEY, staged(tmp_path / "job", b"RIFF"), {}, None
    )
    artifacts.hold([published.id], f"rev:{video.id}:2")
    artifacts.release(f"rev:{video.id}:2")
    assert artifacts.sweep() == 1
    projects.delete_project(project.id)

    with db.read() as conn:
        conn.set_trace_callback(None)
    open_transaction = False
    writes = 0
    for statement in statements:
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb == "BEGIN":
            assert not open_transaction
            open_transaction = True
        elif verb in ("COMMIT", "ROLLBACK"):
            open_transaction = False
        elif verb in WRITE_VERBS:
            assert open_transaction, statement
            writes += 1
    assert not open_transaction
    assert writes > 0


def test_migration_v3_assigns_personal_owner(layout: Layout) -> None:
    version_two = tuple(m for m in registered_migrations() if m.version <= 2)
    database = Database.open(layout.state_db, migrations=version_two)
    job = {
        "id": "j_08c71zekrt8ceaqnmy5jjy5zvn",
        "kind": "draft",
        "state": "queued",
        "project_id": None,
        "video_id": None,
        "base_revision": None,
        "request_digest": "0" * 64,
        "idempotency_key": None,
        "attempt": 1,
        "max_attempts": 3,
        "created_at": "2026-11-14T12:00:00Z",
        "started_at": None,
        "ended_at": None,
        "deadline_at": None,
        "progress": {"stage": None, "done": 0, "total": 0, "waiting_on": "queue"},
        "stages": [],
        "checkpoints": [],
        "usage": [],
        "result": None,
        "error": None,
        "partial": False,
    }
    with database.write() as conn:
        conn.execute(
            "INSERT INTO jobs (id, kind, queue, state, attempt, video_id, created_at, doc) "
            "VALUES (?, 'draft', 'light', 'queued', 1, NULL, ?, ?)",
            (job["id"], job["created_at"], json.dumps(job)),
        )
        conn.execute(
            "INSERT INTO artifacts "
            "(id, kind, digest, bytes, cache_key, root, path, created_at, job_id, media) "
            "VALUES ('a_08c71zekrt8ceaqnmy5jjy5zvn', 'srt', ?, 1, ?, 'cache', "
            "'a/00/x.srt', ?, NULL, '{}')",
            ("0" * 64, CACHE_KEY, job["created_at"]),
        )
        conn.execute(
            "INSERT INTO idempotency "
            "(key, route, request_digest, state, status, body, created_at, expires_at) "
            "VALUES ('migration-key-01', 'POST /api/v1/projects', ?, 'done', 201, '{}', ?, ?)",
            ("0" * 64, job["created_at"], "2027-11-14T12:00:00+00:00"),
        )
    database.close()

    migrated = Database.open(layout.state_db)
    try:
        assert migrated.user_version == LATEST
        with migrated.read() as conn:
            assert conn.execute("SELECT DISTINCT owner_id FROM jobs").fetchall() == [("owner",)]
            assert conn.execute("SELECT DISTINCT owner_id FROM artifacts").fetchall() == [
                ("owner",)
            ]
            doc = json.loads(conn.execute("SELECT doc FROM jobs").fetchone()[0])
            assert doc["owner_id"] == "owner"
            assert Job.model_validate(doc).owner_id == "owner"
            assert conn.execute(
                "SELECT owner_id, key FROM idempotency"
            ).fetchall() == [("owner", "migration-key-01")]
    finally:
        migrated.close()
    assert layout.state_db.with_name("state.db.bak-2").is_file()

    reopened = Database.open(layout.state_db)
    try:
        with reopened.write() as conn:
            conn.execute(
                "INSERT INTO idempotency "
                "(owner_id, key, route, request_digest, state, status, body, created_at, "
                "expires_at) VALUES ('u_0hzb7bexv28termtt2ypc6trzt', 'migration-key-01', "
                "'POST /api/v1/projects', ?, 'done', 201, '{}', ?, ?)",
                ("0" * 64, job["created_at"], "2027-11-14T12:00:00+00:00"),
            )
            assert conn.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0] == 2
    finally:
        reopened.close()

