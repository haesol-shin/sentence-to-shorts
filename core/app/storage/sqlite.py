"""state.db: WAL, busy timeout, short write transactions and ordered SQL migrations.

The tables of version 1 and the migration registration live in this file. A later
version adds one file `migrations/db_v<N>.sql` and nothing else: the registry reads
every such file, requires the versions to be contiguous and applies the pending ones
in order. A migration file holds plain statements without BEGIN or COMMIT. All
pending files run inside one transaction together with the `PRAGMA user_version` bump.

Before pending migrations run on an existing file, the database is copied to
`state.db.bak-<version>`. If any step fails, every pending step is rolled back, the
original and the backup stay as they were, and opening fails so the app does not start.

Writes go through `Database.write()` only. Outside it the connection is query-only,
so a stray write fails instead of running in an implicit long transaction.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 5000
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_FILE = re.compile(r"^db_v([1-9][0-9]*)\.sql$")

SCHEMA_V1 = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX projects_owner ON projects (owner_id, created_at);

CREATE TABLE videos (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    head INTEGER NOT NULL CHECK (head >= 1)
);
CREATE INDEX videos_project ON videos (project_id);

CREATE TABLE revisions (
    video_id TEXT NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    change_id TEXT,
    PRIMARY KEY (video_id, revision)
) WITHOUT ROWID;

CREATE TABLE changes (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    doc TEXT NOT NULL
);
CREATE INDEX changes_video ON changes (video_id);

CREATE TABLE presets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    doc TEXT NOT NULL
);
CREATE INDEX presets_project ON presets (project_id, created_at);

CREATE TABLE activity (
    id INTEGER PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('active', 'waiting')),
    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK (end_ms >= 0)
);
CREATE INDEX activity_video ON activity (video_id);

CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    digest TEXT NOT NULL,
    bytes INTEGER NOT NULL CHECK (bytes >= 1),
    cache_key TEXT NOT NULL,
    root TEXT NOT NULL CHECK (root IN ('data', 'cache')),
    path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    job_id TEXT,
    media TEXT NOT NULL
);
CREATE INDEX artifacts_cache_key ON artifacts (cache_key, created_at);

CREATE TABLE holds (
    holder TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES artifacts (id) ON DELETE CASCADE,
    PRIMARY KEY (holder, artifact_id)
) WITHOUT ROWID;
CREATE INDEX holds_artifact ON holds (artifact_id);
"""


@dataclass(frozen=True)
class Migration:
    version: int
    sql: str


class MigrationFailed(RuntimeError):
    """state.db could not be brought to the app's version. The app must not start."""


def registered_migrations(directory: Path = MIGRATIONS_DIR) -> tuple[Migration, ...]:
    """Version 1 from this file plus every `db_v<N>.sql`, ordered and contiguous."""
    found = [Migration(1, SCHEMA_V1)]
    for path in sorted(directory.glob("db_v*.sql")):
        match = _MIGRATION_FILE.fullmatch(path.name)
        if match is None or int(match.group(1)) == 1:
            raise RuntimeError(f"unexpected migration file name: {path.name}")
        found.append(Migration(int(match.group(1)), path.read_text(encoding="utf-8")))
    found.sort(key=lambda migration: migration.version)
    for expected, migration in enumerate(found, start=1):
        if migration.version != expected:
            raise RuntimeError(f"migration versions are not contiguous at v{expected}")
    return tuple(found)


class Database:
    """One connection, one lock, one write path."""

    def __init__(self, connection: sqlite3.Connection, path: Path) -> None:
        self._conn = connection
        self._lock = threading.RLock()
        self.path = path

    @classmethod
    def open(
        cls, path: Path, *, migrations: Sequence[Migration] | None = None
    ) -> Database:
        steps = tuple(registered_migrations() if migrations is None else migrations)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.is_file() and path.stat().st_size > 0
        conn = sqlite3.connect(
            path,
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = FULL")
            conn.execute("PRAGMA foreign_keys = ON")
            _migrate(conn, path, steps, existed)
            conn.execute("PRAGMA query_only = ON")
        except BaseException:
            conn.close()
            raise
        return cls(conn, path)

    @property
    def user_version(self) -> int:
        with self.read() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """A short IMMEDIATE transaction. Commit on success, roll back on any error."""
        with self._lock:
            conn = self._conn
            if conn.in_transaction:
                raise RuntimeError("nested write transaction")
            conn.execute("PRAGMA query_only = OFF")
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            finally:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                conn.execute("PRAGMA query_only = ON")

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _migrate(
    conn: sqlite3.Connection, path: Path, steps: tuple[Migration, ...], existed: bool
) -> None:
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    latest = steps[-1].version if steps else 0
    if current > latest:
        raise MigrationFailed(f"state.db version {current} is newer than supported {latest}")
    pending = [step for step in steps if step.version > current]
    if not pending:
        return
    if existed:
        _backup(conn, path.with_name(f"{path.name}.bak-{current}"))
    # One transaction for every pending step: a later failure also undoes the
    # earlier ones, so the original stays at its starting version.
    script = "\n;\n".join(step.sql for step in pending)
    target = pending[-1].version
    try:
        conn.executescript(
            f"BEGIN IMMEDIATE;\n{script}\n;\nPRAGMA user_version = {target};\nCOMMIT;"
        )
    except sqlite3.Error as error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        log.error(
            "state.db migration failed",
            extra={"event": "db_migration_failed", "stage": f"db_v{target}"},
        )
        raise MigrationFailed(f"state.db migration to v{target} failed") from error
    log.info("state.db migrated", extra={"event": "db_migrated", "stage": f"db_v{target}"})


def _backup(conn: sqlite3.Connection, target: Path) -> None:
    """Consistent copy through the backup API, so pages still in the WAL are included."""
    partial = target.with_name(target.name + ".tmp")
    partial.unlink(missing_ok=True)
    copy = sqlite3.connect(partial)
    try:
        conn.backup(copy)
    finally:
        copy.close()
    os.replace(partial, target)


__all__ = [
    "BUSY_TIMEOUT_MS",
    "Database",
    "Migration",
    "MigrationFailed",
    "SCHEMA_V1",
    "registered_migrations",
]
