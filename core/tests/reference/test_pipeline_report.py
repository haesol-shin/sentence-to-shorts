"""Reference reports survive every successful plan-settlement branch."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.ports import ReferenceOutcome
from app.schemas.change import ChangeStatus, SetOp, Target
from app.schemas.common import Origin
from app.schemas.job import JobKind
from app.schemas.video import Measured, ReferenceKind, ReferenceStatus, ReferenceSummary
from app.services.pipeline.dependencies import plan_change
from app.services.pipeline.run import run
from app.services.reference.service import ReferenceReport, StyleHints
from tests.pipeline.support import Harness, build_harness


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    opened = build_harness(tmp_path)
    try:
        yield opened
    finally:
        opened.close()


@pytest.mark.parametrize(
    ("branch", "expected_status"),
    [
        ("no_plan", None),
        ("apply", "applied"),
        ("confirmation", "proposed"),
        ("already_applied", "applied"),
        ("rejected", "rejected"),
        ("already_stale", "stale"),
        ("base_mismatch", "stale"),
        ("head_advanced", "stale"),
    ],
)
def test_20_reference_report_survives_plan_settlement(
    harness: Harness, branch: str, expected_status: str | None
) -> None:
    video = harness.video
    report = ReferenceReport(
        summary=ReferenceSummary(
            id=harness.projects.new_id("rf"),
            kind=ReferenceKind.file,
            host=None,
            status=ReferenceStatus.analyzed,
            source_deleted=True,
            measured=Measured(duration_ms=3000, scene_count=3, silence_ratio=0.2, has_bgm=True),
            style=None,
        ),
        style_hints=StyleHints(palette=["#123456"]),
        kept_user_values=["/settings/format/layout"],
    )
    plan = None
    if branch != "no_plan":
        op = SetOp(
            op="set", path="/settings/format/humor", value="light", origin=Origin.reference
        )
        if branch == "confirmation":
            scene = video.scenes[video.scene_order[0]]
            lines = [
                line.model_copy(update={"display_text": "A synthetic reference line"}).model_dump(
                    mode="json"
                )
                for line in scene.lines
            ]
            op = SetOp(
                op="set", path=f"/scenes/{scene.id}/lines", value=lines, origin=Origin.reference
            )
        plan = plan_change(
            video, [op], "reference", Target(scene_id=None, pointer=None), harness.services
        )
        if branch == "rejected":
            plan = plan.model_copy(update={"status": ChangeStatus.rejected})
        elif branch == "already_stale":
            plan = plan.model_copy(update={"status": ChangeStatus.stale})
        harness.projects.put_change(plan)
        if branch == "already_applied":
            harness.project_service.commit(plan, video.revision)
        elif branch == "base_mismatch":
            video = harness.revise(video, topic="A newer synthetic topic")
        elif branch == "head_advanced":
            harness.revise(video, topic="A newer synthetic topic")
    harness.reference.outcome = ReferenceOutcome(
        change_id=None if plan is None else plan.id, reference=report
    )
    job = harness.job(
        JobKind.reference,
        video=video,
        input={"base_revision": video.revision, "url": "https://example.invalid/reference"},
    )

    result = run(job, harness.context(job), harness.services)

    assert result["status"] == expected_status
    assert result["change_id"] == (None if plan is None else plan.id)
    assert json.loads(json.dumps(result))["reference"] == report.model_dump(mode="json")
    head = harness.projects.get_video(video.id)
    if expected_status == "applied":
        assert result["applied_revision"] == head.revision
        assert head.settings.format.humor.value == "light"
    elif plan is not None:
        assert harness.projects.get_change(plan.id).status.value == expected_status
        assert head.settings.format.humor == video.settings.format.humor
