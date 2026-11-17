"""GET /videos/{vid}/metrics reads cost from the usage ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from app.jobs import LIGHT
from app.schemas.job import JobKind, JobState, Stage
from app.schemas.usage import UsageEvent
from app.storage.usage import PriceTable, TokenPrice
from tests.jobs.support import new_job

OWNER = "owner"


def test_cost_rounds_once_per_line(client: TestClient) -> None:
    project = client.post(
        "/api/v1/projects", json={"title": None, "language": "ko"}
    ).json()
    video = client.post(
        f"/api/v1/projects/{project['id']}/videos",
        json={"from_video_id": None, "preset_id": None},
    ).json()
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    runtime.usage._prices = PriceTable(
        version="test",
        llm={
            ("fixture", "fixture"): TokenPrice(
                input=1_000_000, output=0, cache_read=0, cache_write=0
            )
        },
    )
    job = new_job(JobKind.draft, video_id=video["id"]).model_copy(
        update={"state": JobState.succeeded}
    )
    event = UsageEvent(
        id=f"{job.id}:1:1:0",
        owner_id=OWNER,
        occurred_at=datetime.now(UTC),
        job_id=job.id,
        attempt=1,
        call_seq=1,
        try_index=0,
        stage=Stage.llm_draft,
        provider="fixture",
        model="fixture",
        credential_id=None,
        input_tokens=2,
        output_tokens=None,
        cache_read_tokens=None,
        cache_write_tokens=None,
        outcome="ok",
        price_version="test",
    )
    payload: dict[str, Any] = event.model_dump(mode="json")
    with runtime.state_db.write() as conn:
        conn.execute(
            "INSERT INTO jobs (id, owner_id, kind, queue, state, attempt, video_id, "
            "created_at, doc) VALUES (?, ?, 'draft', ?, 'succeeded', 1, ?, ?, ?)",
            (
                job.id,
                OWNER,
                LIGHT,
                video["id"],
                "2026-11-17T00:00:00+00:00",
                job.model_dump_json(),
            ),
        )
        conn.execute(
            "INSERT INTO usage_events (id, owner_id, occurred_at, job_id, attempt, "
            "call_seq, try_index, stage, provider, model, credential_id, input_tokens, "
            "output_tokens, cache_read_tokens, cache_write_tokens, outcome, price_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payload["id"],
                payload["owner_id"],
                payload["occurred_at"],
                payload["job_id"],
                payload["attempt"],
                payload["call_seq"],
                payload["try_index"],
                payload["stage"],
                payload["provider"],
                payload["model"],
                payload["credential_id"],
                payload["input_tokens"],
                payload["output_tokens"],
                payload["cache_read_tokens"],
                payload["cache_write_tokens"],
                payload["outcome"],
                payload["price_version"],
            ),
        )
    metrics = client.get(f"/api/v1/videos/{video['id']}/metrics").json()
    assert metrics["cost_micro_usd"] == 2
    assert "cost_usd" not in metrics
