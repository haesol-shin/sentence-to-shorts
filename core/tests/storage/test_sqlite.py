"""state.db: migrations keep the original on failure, writes stay inside short
transactions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

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
        "tts_wav", CACHE_KEY, staged(tmp_path / "job", b"RIFF"), {}, None
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
