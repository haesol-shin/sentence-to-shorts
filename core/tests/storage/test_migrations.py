"""Stored document migrations: before and after fixtures plus version boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ports import AppError
from app.schemas.artifact import Timing
from app.schemas.change import ChangePlan
from app.schemas.job import Job
from app.schemas.project import Project
from app.schemas.video import Video
from app.storage.migrations import (
    CHANGE_DOCUMENT_VERSION,
    PROJECT_DOCUMENT_VERSION,
    VIDEO_DOCUMENT_VERSION,
    upgrade_document,
)
from app.storage.migrations.v1_to_v2 import migrate
from app.storage.paths import Layout
from app.storage.sqlite import Database, registered_migrations
from tests.conftest import load_json

MIGRATIONS = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "migrations"
JOB_ID = "j_08c71zekrt8ceaqnmy5jjy5zvn"


def _cue(item_id: str) -> dict:
    return {
        "sfx_id": {"id": item_id, "revision": "0" * 64},
        "line_id": "l_079jmk94bf8vj82ct90jqj44km",
        "at": "start",
        "offset_ms": 0,
    }


def test_v1_video_drops_only_builtin_typing_cues() -> None:
    before = load_json("contracts/migrations/video_v1_typing_cue.json")
    after = load_json("contracts/migrations/video_v2_typing_cue.json")
    assert migrate(before) == after
    assert upgrade_document(before, VIDEO_DOCUMENT_VERSION) == after
    assert Video.model_validate(after).schema_version == 2


def test_v1_change_drops_builtin_typing_cues_in_nested_scenes() -> None:
    visual = {
        "background_id": "bg_village",
        "characters": [],
        "elements": [],
        "sfx": [_cue("typing_keys"), _cue("pop"), _cue("typing_fast")],
        "transition_in": "cut",
    }
    change = {
        "schema_version": 1,
        "id": "c_0t2wvk16pb9s0a453j9s6540mg",
        "video_id": "v_0hzb7bexv28termtt2ypc6trzt",
        "base_revision": 1,
        "ops": [
            {
                "op": "set",
                "path": "/scenes/s_0nzvrzf0tp9wba44f6yvh6nzpr/visual",
                "value": visual,
                "origin": "user",
            }
        ],
    }
    migrated = migrate(change)
    assert migrated["schema_version"] == 2
    cues = migrated["ops"][0]["value"]["sfx"]
    assert [cue["sfx_id"]["id"] for cue in cues] == ["pop"]


def test_v1_change_op_values_drop_builtin_typing_cues() -> None:
    before = load_json("contracts/migrations/change_v1_typing_cue_ops.json")
    after = load_json("contracts/migrations/change_v2_typing_cue_ops.json")
    assert migrate(before) == after
    assert upgrade_document(before, CHANGE_DOCUMENT_VERSION) == after
    assert ChangePlan.model_validate(after).schema_version == 2


def test_v1_change_op_values_keep_other_sfx_cues() -> None:
    before = load_json("contracts/migrations/change_v1_other_sfx_ops.json")
    migrated = migrate(before)
    assert migrated["schema_version"] == 2
    assert migrated["ops"] == before["ops"]
    assert ChangePlan.model_validate(migrated).schema_version == 2


def test_v1_document_without_cues_keeps_its_version() -> None:
    project = load_json("contracts/valid/project_min.json")
    migrated = upgrade_document(project, PROJECT_DOCUMENT_VERSION)
    assert migrated["schema_version"] == 1
    assert Project.model_validate(migrated).schema_version == 1


def test_timing_v1_is_not_reused() -> None:
    before = load_json("contracts/migrations/timing_v1.json")
    with pytest.raises(ValueError):
        Timing.model_validate(before)


def test_a_document_newer_than_its_type_is_refused() -> None:
    project = load_json("contracts/valid/project_min.json")
    project["schema_version"] = 2
    with pytest.raises(AppError) as refused:
        upgrade_document(project, PROJECT_DOCUMENT_VERSION)
    assert refused.value.code == "unsupported_version"
    assert refused.value.detail == {"found": 2, "supported": 1}


def test_migration_is_idempotent() -> None:
    after = load_json("contracts/migrations/video_v2_typing_cue.json")
    assert migrate(after) == after


def _job_doc() -> dict:
    return {
        "id": JOB_ID,
        "kind": "draft",
        "owner_id": "owner",
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
        "usage": [
            {
                "stage": "llm_draft",
                "provider": "fixture",
                "model": "fixture",
                "effort": None,
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": None,
                "cost_usd": None,
                "wall_ms": 12,
                "retries": 0,
            }
        ],
        "result": None,
        "error": None,
        "partial": False,
    }


def _v3_with_job(layout: Layout, doc: dict) -> None:
    version_three = tuple(m for m in registered_migrations() if m.version <= 3)
    database = Database.open(layout.state_db, migrations=version_three)
    try:
        with database.write() as conn:
            conn.execute(
                "INSERT INTO jobs (id, owner_id, kind, queue, state, attempt, video_id, "
                "created_at, doc) VALUES (?, 'owner', 'draft', 'light', 'queued', 1, NULL, "
                "?, ?)",
                (JOB_ID, "2026-11-14T12:00:00Z", json.dumps(doc)),
            )
    finally:
        database.close()


def test_migration_v4_drops_cost_usd_and_creates_events(layout: Layout) -> None:
    _v3_with_job(layout, _job_doc())
    migrated = Database.open(layout.state_db)
    try:
        assert migrated.user_version == registered_migrations()[-1].version
        with migrated.read() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            assert "usage_events" in tables
            doc = json.loads(conn.execute("SELECT doc FROM jobs").fetchone()[0])
        job = Job.model_validate(doc)
        assert "cost_usd" not in doc["usage"][0]
        assert job.usage[0].cache_write_tokens is None
        assert job.usage[0].input_tokens == 10
    finally:
        migrated.close()
    assert layout.state_db.with_name("state.db.bak-3").is_file()


def test_migration_v4_keeps_an_empty_usage_list(layout: Layout) -> None:
    doc = _job_doc()
    doc["usage"] = []
    _v3_with_job(layout, doc)
    migrated = Database.open(layout.state_db)
    try:
        with migrated.read() as conn:
            stored = json.loads(conn.execute("SELECT doc FROM jobs").fetchone()[0])
        assert stored["usage"] == []
    finally:
        migrated.close()
