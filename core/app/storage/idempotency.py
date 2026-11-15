"""Idempotency-Key records in state.db (CONTRACTS section 3).

A request reserves its key with `begin`. The first request gets `None` and runs; it
then stores the response with `complete`, or frees the key with `abort` when it
fails before a response exists. A repeat with the same route and request digest gets
the stored response back. A repeat with another route or digest is refused with
`idempotency_mismatch` (HTTP 409). A repeat that arrives while the first request is
still running is refused with `IdempotencyInProgress`.

Records expire after the configured hours (24 by default). An expired record is
treated as absent and replaced. The router decides which requests use this store.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ports import AppError
from app.schemas.common import DIGEST_PATTERN
from app.storage.projects import utc_text
from app.storage.sqlite import Database

DEFAULT_TTL_HOURS = 24
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_DIGEST = re.compile(DIGEST_PATTERN)


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: Any


class IdempotencyInProgress(Exception):
    """The same key and request are still running; the response does not exist yet."""


def _now() -> datetime:
    return datetime.now(UTC)


class SqliteIdempotencyStore:
    def __init__(
        self,
        db: Database,
        *,
        ttl_hours: int = DEFAULT_TTL_HOURS,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        if ttl_hours < 1:
            raise ValueError("ttl_hours must be at least 1")
        self._db = db
        self._ttl = timedelta(hours=ttl_hours)
        self._clock = clock

    def begin(self, key: str, route: str, request_digest: str) -> StoredResponse | None:
        """Reserve the key, or return the stored response of the same request."""
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError("invalid idempotency key")
        if not _DIGEST.fullmatch(request_digest):
            raise ValueError("request digest is not a SHA-256 digest")
        now = self._clock()
        with self._db.write() as conn:
            row = conn.execute(
                "SELECT route, request_digest, state, status, body, expires_at "
                "FROM idempotency WHERE key = ?",
                (key,),
            ).fetchone()
            if row is not None and datetime.fromisoformat(row[5]) > now:
                if row[0] != route or row[1] != request_digest:
                    raise AppError("idempotency_mismatch")
                if row[2] != "done":
                    raise IdempotencyInProgress(key)
                return StoredResponse(status=int(row[3]), body=json.loads(row[4]))
            conn.execute(
                "INSERT OR REPLACE INTO idempotency "
                "(key, route, request_digest, state, status, body, created_at, expires_at) "
                "VALUES (?, ?, ?, 'pending', NULL, NULL, ?, ?)",
                (key, route, request_digest, utc_text(now), utc_text(now + self._ttl)),
            )
        return None

    def complete(self, key: str, route: str, request_digest: str, status: int, body: Any) -> None:
        """Store the response of a reserved request. Later repeats get it back as is."""
        text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._db.write() as conn:
            updated = conn.execute(
                "UPDATE idempotency SET state = 'done', status = ?, body = ? "
                "WHERE key = ? AND route = ? AND request_digest = ? AND state = 'pending'",
                (status, text, key, route, request_digest),
            ).rowcount
        if updated != 1:
            raise RuntimeError("idempotency key was not reserved by this request")

    def abort(self, key: str, route: str, request_digest: str) -> None:
        """Free a reservation whose request failed before it had a response."""
        with self._db.write() as conn:
            conn.execute(
                "DELETE FROM idempotency "
                "WHERE key = ? AND route = ? AND request_digest = ? AND state = 'pending'",
                (key, route, request_digest),
            )

    def drop_pending(self) -> int:
        """Free every reservation left by a process that stopped mid-request. Run at start."""
        with self._db.write() as conn:
            return conn.execute("DELETE FROM idempotency WHERE state = 'pending'").rowcount

    def purge_expired(self) -> int:
        with self._db.write() as conn:
            return conn.execute(
                "DELETE FROM idempotency WHERE expires_at <= ?", (utc_text(self._clock()),)
            ).rowcount


__all__ = [
    "DEFAULT_TTL_HOURS",
    "IdempotencyInProgress",
    "SqliteIdempotencyStore",
    "StoredResponse",
]
