"""Reference summaries are stored on the analyzed revision and survive later edits."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ports import ReferenceOutcome
from app.schemas.change import SetOp, Target
from app.schemas.common import Origin
from app.schemas.video import (
    CreatedBy,
    Measured,
    ReferenceHost,
    ReferenceKind,
    ReferenceStatus,
    ReferenceSummary,
    Video,
)
from app.services.pipeline.dependencies import plan_change
from app.services.project import revision
from app.services.reference.service import ReferenceReport, StyleHints

LINK = "https://www.youtube.com/watch?v=synthetic-reference"


def _new_video(client: TestClient) -> dict[str, Any]:
    project = client.post(
        "/api/v1/projects", json={"title": "Reference summary", "language": "en"}
    )
    assert project.status_code == 201, project.text
    response = client.post(
        f"/api/v1/projects/{project.json()['id']}/videos",
        json={"from_video_id": None, "preset_id": None},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _report(runtime: Any) -> ReferenceReport:
    return ReferenceReport(
        summary=ReferenceSummary(
            id=runtime.project_store.new_id("rf"),
            kind=ReferenceKind.link,
            host=ReferenceHost.youtube,
            status=ReferenceStatus.analyzed,
            source_deleted=True,
            measured=Measured(
                duration_ms=3000, scene_count=4, silence_ratio=0.25, has_bgm=False
            ),
            style=None,
        ),
        style_hints=StyleHints(palette=["#112233"]),
        kept_user_values=[],
    )


def _fake_reference(
    monkeypatch: pytest.MonkeyPatch, runtime: Any, analyze: Any
) -> None:
    def ingest(_upload: Any, _url: Any, *, ctx: Any):
        source = ctx.job_dir / "reference-source.bin"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"synthetic-reference")
        return source

    monkeypatch.setattr(runtime.services.reference, "ingest", ingest)
    monkeypatch.setattr(runtime.services.reference, "analyze", analyze)


def _run_reference(client: TestClient, video: dict[str, Any]) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    response = client.post(
        f"/api/v1/videos/{video['id']}/references/link",
        json={"base_revision": video["revision"], "url": LINK},
    )
    assert response.status_code == 202, response.text
    job = response.json()
    while True:
        response = client.get(f"/api/v1/jobs/{job['id']}")
        assert response.status_code == 200, response.text
        finished = response.json()
        if finished["state"] in {"succeeded", "failed", "cancelled"}:
            return finished
        assert time.monotonic() < deadline, "reference job did not terminate"
        time.sleep(0.02)


def _view(client: TestClient, video_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/videos/{video_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_20_no_plan_summary_is_the_next_revision_and_reads_back(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    video = _new_video(client)
    report = _report(runtime)

    def analyze(_source: Any, _video: Video, *, ctx: Any) -> ReferenceOutcome:
        return ReferenceOutcome(change_id=None, reference=report)

    _fake_reference(monkeypatch, runtime, analyze)
    job = _run_reference(client, video)

    assert job["state"] == "succeeded", job.get("error")
    assert job["result"]["status"] is None
    assert job["result"]["change_id"] is None
    assert job["result"]["applied_revision"] is None
    assert job["result"]["reference"] == report.model_dump(mode="json")

    view = _view(client, video["id"])
    stored = view["video"]
    assert stored["revision"] == video["revision"] + 1
    assert stored["reference"] == report.summary.model_dump(mode="json")
    assert stored["topic"] == video["topic"]

    old = runtime.project_store.get_video(video["id"], video["revision"])
    assert old.reference is None


def test_20_auto_applied_plan_keeps_summary_on_the_applied_head(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    video = _new_video(client)
    report = _report(runtime)

    def analyze(_source: Any, analyzed: Video, *, ctx: Any) -> ReferenceOutcome:
        op = SetOp(
            op="set",
            path="/settings/format/humor",
            value="light",
            origin=Origin.reference,
        )
        plan = plan_change(
            analyzed, [op], "reference", Target(scene_id=None, pointer=None), runtime.services
        )
        assert not plan.requires_confirmation
        runtime.project_store.put_change(plan)
        return ReferenceOutcome(change_id=plan.id, reference=report)

    _fake_reference(monkeypatch, runtime, analyze)
    job = _run_reference(client, video)

    assert job["state"] == "succeeded", job.get("error")
    assert job["result"]["status"] == "applied"
    assert job["result"]["applied_revision"] is not None

    view = _view(client, video["id"])
    current = view["video"]
    assert current["revision"] == job["result"]["applied_revision"]
    assert current["revision"] == video["revision"] + 2
    assert current["reference"] == report.summary.model_dump(mode="json")
    assert current["settings"]["format"]["humor"] == "light"

    old = runtime.project_store.get_video(video["id"], video["revision"])
    assert old.reference is None
    assert old.settings.format.humor.value != "light"


def test_20_confirmation_plan_tracks_the_summary_revision_and_apply_keeps_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    video = _new_video(client)
    report = _report(runtime)
    character = video["settings"]["visual"]["character"]
    assert character is not None
    assert character["slots"]["body"] != "body_round"
    changed = {
        **character,
        "slots": {**character["slots"], "body": "body_round"},
    }

    def analyze(_source: Any, analyzed: Video, *, ctx: Any) -> ReferenceOutcome:
        op = SetOp(
            op="set",
            path="/settings/visual/character",
            value=changed,
            origin=Origin.reference,
        )
        plan = plan_change(
            analyzed, [op], "reference", Target(scene_id=None, pointer=None), runtime.services
        )
        assert plan.requires_confirmation
        assert "character" in [key.value for key in plan.effects.locked_keys]
        runtime.project_store.put_change(plan)
        return ReferenceOutcome(change_id=plan.id, reference=report)

    _fake_reference(monkeypatch, runtime, analyze)
    job = _run_reference(client, video)

    assert job["state"] == "succeeded", job.get("error")
    assert job["result"]["status"] == "proposed"
    assert job["result"]["applied_revision"] is None
    change_id = job["result"]["change_id"]
    assert change_id is not None

    view = _view(client, video["id"])
    current = view["video"]
    assert current["revision"] == video["revision"] + 1
    assert current["reference"] == report.summary.model_dump(mode="json")
    assert view["pending_change"] == change_id

    plan = client.get(f"/api/v1/changes/{change_id}")
    assert plan.status_code == 200, plan.text
    assert plan.json()["status"] == "proposed"
    assert plan.json()["base_revision"] == current["revision"]

    applied = client.post(
        f"/api/v1/changes/{change_id}/apply",
        json={"base_revision": current["revision"]},
    )
    assert applied.status_code == 200, applied.text
    after = applied.json()
    assert after["revision"] == current["revision"] + 1
    assert after["reference"] == report.summary.model_dump(mode="json")
    assert after["settings"]["visual"]["character"]["slots"]["body"] == "body_round"


def test_20_head_advanced_during_analysis_is_not_overwritten(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    video = _new_video(client)
    report = _report(runtime)

    def analyze(_source: Any, analyzed: Video, *, ctx: Any) -> ReferenceOutcome:
        newer = analyzed.model_copy(update={"topic": "A newer user topic"})
        runtime.project_store.append_revision(
            revision.next_revision(newer, analyzed, CreatedBy.system)
        )
        return ReferenceOutcome(change_id=None, reference=report)

    _fake_reference(monkeypatch, runtime, analyze)
    job = _run_reference(client, video)

    assert job["state"] == "succeeded", job.get("error")
    assert job["result"]["reference"] == report.model_dump(mode="json")
    view = _view(client, video["id"])
    assert view["video"]["revision"] == video["revision"] + 1
    assert view["video"]["topic"] == "A newer user topic"
    assert view["video"]["reference"] is None


def test_20_append_conflict_keeps_the_winning_head_and_its_content(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    video = _new_video(client)
    report = _report(runtime)
    real_append = runtime.project_store.append_revision
    raced = False

    def append(candidate: Video) -> Video:
        nonlocal raced
        if not raced and candidate.reference is not None:
            raced = True
            head = runtime.project_store.get_video(candidate.id)
            newer = head.model_copy(update={"topic": "The concurrent winner"})
            real_append(revision.next_revision(newer, head, CreatedBy.system))
        return real_append(candidate)

    monkeypatch.setattr(runtime.project_store, "append_revision", append)

    def analyze(_source: Any, _video: Video, *, ctx: Any) -> ReferenceOutcome:
        return ReferenceOutcome(change_id=None, reference=report)

    _fake_reference(monkeypatch, runtime, analyze)
    job = _run_reference(client, video)

    assert raced
    assert job["state"] == "succeeded", job.get("error")
    assert job["result"]["reference"] == report.model_dump(mode="json")
    view = _view(client, video["id"])
    assert view["video"]["revision"] == video["revision"] + 1
    assert view["video"]["topic"] == "The concurrent winner"
    assert view["video"]["reference"] is None
