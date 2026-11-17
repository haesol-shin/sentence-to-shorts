"""A second server must never recover a live server's idempotency reservations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.access.idempotency import IdempotencyGate
from app.ports import canonical_digest
from app.storage.idempotency import IdempotencyInProgress

KEY = "instance-request-01"
OWNER = "owner"
ROUTE = "POST /api/v1/projects"
DIGEST = canonical_digest({"title": "synthetic"})


def test_second_gate_preserves_live_reservation_and_response(tmp_path: Path) -> None:
    path = tmp_path / "data" / "state.db"
    owner = IdempotencyGate.open(path, ttl_hours=24)
    try:
        assert owner.store.begin(OWNER, KEY, ROUTE, DIGEST) is None
        with pytest.raises(RuntimeError, match="already in use"):
            IdempotencyGate.open(path, ttl_hours=24)
        with pytest.raises(IdempotencyInProgress):
            owner.store.begin(OWNER, KEY, ROUTE, DIGEST)
        owner.store.complete(OWNER, KEY, ROUTE, DIGEST, 201, {"result": "created"})
    finally:
        owner.close()
    reopened = IdempotencyGate.open(path, ttl_hours=24)
    try:
        response = reopened.store.begin(OWNER, KEY, ROUTE, DIGEST)
        assert response is not None
        assert response.status == 201
        assert response.body == {"result": "created"}
    finally:
        reopened.close()


def _child(script: str, path: Path) -> subprocess.CompletedProcess[str]:
    core = Path(__file__).resolve().parents[2]
    return subprocess.run(
        [sys.executable, "-c", script, str(path)],
        cwd=core,
        env={**os.environ, "PYTHONPATH": str(core)},
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )


def test_second_process_cannot_erase_a_live_reservation(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    owner = IdempotencyGate.open(path, ttl_hours=24)
    try:
        owner.store.begin(OWNER, KEY, ROUTE, DIGEST)
        child = _child(
            "from pathlib import Path\n"
            "import sys\n"
            "from app.access.idempotency import IdempotencyGate\n"
            "try:\n"
            "    gate = IdempotencyGate.open(Path(sys.argv[1]), ttl_hours=24)\n"
            "except RuntimeError as error:\n"
            "    assert 'already in use' in str(error)\n"
            "    print('locked')\n"
            "else:\n"
            "    gate.close()\n"
            "    raise AssertionError('second server acquired the data store')\n",
            path,
        )
        assert child.stdout.strip() == "locked"
        with pytest.raises(IdempotencyInProgress):
            owner.store.begin(OWNER, KEY, ROUTE, DIGEST)
        owner.store.complete(OWNER, KEY, ROUTE, DIGEST, 201, {"result": "created"})
    finally:
        owner.close()


def test_process_exit_releases_lock_and_recovers_abandoned_request(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    _child(
        "from pathlib import Path\n"
        "import os, sys\n"
        "from app.access.idempotency import IdempotencyGate\n"
        "gate = IdempotencyGate.open(Path(sys.argv[1]), ttl_hours=24)\n"
        f"gate.store.begin({OWNER!r}, {KEY!r}, {ROUTE!r}, {DIGEST!r})\n"
        "os._exit(0)\n",
        path,
    )
    owner = IdempotencyGate.open(path, ttl_hours=24)
    try:
        assert owner.store.begin(OWNER, KEY, ROUTE, DIGEST) is None
        owner.store.complete(OWNER, KEY, ROUTE, DIGEST, 201, {"result": "recovered"})
    finally:
        owner.close()


def test_database_open_failure_releases_instance_lock(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "state.db"
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise OSError("database unavailable")

        patch.setattr("app.access.idempotency.Database.open", fail)
        with pytest.raises(OSError, match="database unavailable"):
            IdempotencyGate.open(path, ttl_hours=24)
    owner = IdempotencyGate.open(path, ttl_hours=24)
    try:
        assert owner.store.begin(OWNER, KEY, ROUTE, DIGEST) is None
    finally:
        owner.close()
