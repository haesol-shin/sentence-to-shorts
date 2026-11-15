"""Idempotency-Key records: replay, mismatch, in-flight repeat and 24 hour expiry."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.main import STATUS_BY_CODE
from app.ports import AppError, canonical_digest
from app.storage.idempotency import IdempotencyInProgress, SqliteIdempotencyStore
from app.storage.sqlite import Database

KEY = "key_0123456789"
ROUTE = "POST /api/v1/videos/{vid}/jobs/generate"
BODY = canonical_digest({"base_revision": 3})
OTHER_BODY = canonical_digest({"base_revision": 4})


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database.open(tmp_path / "state.db")
    yield database
    database.close()


def test_idempotency_same_key_and_body_returns_the_same_response(db: Database) -> None:
    store = SqliteIdempotencyStore(db)
    assert store.begin(KEY, ROUTE, BODY) is None
    store.complete(KEY, ROUTE, BODY, 202, {"id": "j_01jdq7c3v8m4n5p6q7r8s9t0vw", "n": 1})

    first = store.begin(KEY, ROUTE, BODY)
    second = store.begin(KEY, ROUTE, BODY)
    assert first is not None and second is not None
    assert (first.status, first.body) == (202, {"id": "j_01jdq7c3v8m4n5p6q7r8s9t0vw", "n": 1})
    assert second == first


def test_idempotency_other_body_or_route_is_409(db: Database) -> None:
    store = SqliteIdempotencyStore(db)
    store.begin(KEY, ROUTE, BODY)
    store.complete(KEY, ROUTE, BODY, 202, {"ok": True})

    with pytest.raises(AppError) as body:
        store.begin(KEY, ROUTE, OTHER_BODY)
    with pytest.raises(AppError) as route:
        store.begin(KEY, "POST /api/v1/projects", BODY)
    assert body.value.code == route.value.code == "idempotency_mismatch"
    assert STATUS_BY_CODE[body.value.code] == 409


def test_idempotency_repeat_while_running_is_refused_until_aborted(db: Database) -> None:
    store = SqliteIdempotencyStore(db)
    assert store.begin(KEY, ROUTE, BODY) is None
    with pytest.raises(IdempotencyInProgress):
        store.begin(KEY, ROUTE, BODY)
    store.abort(KEY, ROUTE, BODY)
    assert store.begin(KEY, ROUTE, BODY) is None
    assert store.drop_pending() == 1
    assert store.begin(KEY, ROUTE, BODY) is None


def test_idempotency_key_expires_after_24_hours(db: Database) -> None:
    clock = Clock()
    store = SqliteIdempotencyStore(db, clock=clock)
    store.begin(KEY, ROUTE, BODY)
    store.complete(KEY, ROUTE, BODY, 202, {"ok": True})

    clock.now += timedelta(hours=23, minutes=59)
    with pytest.raises(AppError):
        store.begin(KEY, ROUTE, OTHER_BODY)

    clock.now += timedelta(minutes=1)
    assert store.begin(KEY, ROUTE, OTHER_BODY) is None
    store.abort(KEY, ROUTE, OTHER_BODY)

    store.begin("key_other_0001", ROUTE, BODY)
    clock.now += timedelta(hours=24)
    assert store.purge_expired() == 1


def test_idempotency_rejects_a_malformed_key(db: Database) -> None:
    with pytest.raises(ValueError):
        SqliteIdempotencyStore(db).begin("short", ROUTE, BODY)
