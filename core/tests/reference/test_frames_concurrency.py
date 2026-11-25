"""Kept reference frames survive a style job started before the summary is stored."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ports import JobContext, ReferenceOutcome, StyleFrames
from app.schemas.job import JobKind
from app.schemas.video import (
    Measured,
    ReferenceKind,
    ReferenceLook,
    ReferenceStatus,
    ReferenceSummary,
    Video,
)
from app.services.pipeline.run import run
from app.services.reference.service import ReferenceService
from app.storage.reference import FileReferenceFrames
from tests.pipeline.support import Harness, build_harness


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    opened = build_harness(tmp_path)
    try:
        yield opened
    finally:
        opened.close()


def _summary(harness: Harness) -> ReferenceSummary:
    return ReferenceSummary(
        id=harness.projects.new_id("rf"),
        kind=ReferenceKind.file,
        host=None,
        status=ReferenceStatus.analyzed,
        source_deleted=True,
        measured=Measured(duration_ms=3000, scene_count=3, silence_ratio=0.2, has_bgm=False),
        style=None,
    )


def _run(
    harness: Harness, kind: JobKind, video: Video, payload: dict[str, Any]
) -> dict[str, object]:
    job = harness.job(kind, video=video, input=payload)
    return run(job, harness.context(job), harness.services)


class _RacingReference(ReferenceService):
    """Reference work whose kept frames land before the summary that points at them.

    ``between`` runs once the frames are on disk and before the job returns its
    summary, which is the window a concurrent style job runs in.
    """

    def __init__(
        self, harness: Harness, summary: ReferenceSummary, between: Callable[[], None]
    ) -> None:
        super().__init__(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            catalog=harness.catalog,
            project_store=harness.projects,
            frames=FileReferenceFrames(harness.layout),
            cache_dir=harness.layout.cache,
            max_upload_bytes=1,
            max_upload_ms=1,
        )
        self.summary = summary
        self.between = between
        self.sent = [b"\x89PNG synthetic reference"]

    def ingest(self, upload: Path | None, url: str | None, *, ctx: JobContext) -> Path:
        return ctx.job_dir / "synthetic-reference.mp4"

    def analyze(self, source: Path, video: Video, *, ctx: JobContext) -> ReferenceOutcome:
        names = self._keep(video, self.summary.id, self.sent, [1])
        self.summary = self.summary.model_copy(
            update={"style": ReferenceLook(palette=["#112233"], frames=names)}
        )
        self.between()
        return ReferenceOutcome(
            change_id=None,
            reference=SimpleNamespace(
                summary=self.summary, style_hints=None, kept_user_values=[]
            ),
        )


def test_20_a_style_job_before_the_reference_summary_keeps_frames(
    harness: Harness,
) -> None:
    summary = _summary(harness)
    started: list[int] = []

    def start_style_job() -> None:
        head = harness.projects.get_video(harness.video.id)
        assert head.reference is None
        started.append(head.revision)
        _run(
            harness,
            JobKind.style,
            head,
            {
                "video_id": head.id,
                "base_revision": head.revision,
                "instruction": "참고 그림체",
                "base_style": None,
                "use_reference": False,
            },
        )

    reference = _RacingReference(harness, summary, start_style_job)
    harness.services = replace(harness.services, reference=reference)
    video = harness.video

    _run(
        harness,
        JobKind.reference,
        video,
        {"base_revision": video.revision, "url": "https://example.invalid/ref"},
    )

    assert started == [video.revision]
    stored = harness.projects.get_video(video.id)
    assert stored.reference is not None and stored.reference.id == summary.id
    kept = FileReferenceFrames(harness.layout).get(
        video.project_id, video.id, summary.id, ["frame_0.png"]
    )
    assert kept == reference.sent

    result = _run(
        harness,
        JobKind.style,
        stored,
        {
            "video_id": stored.id,
            "base_revision": stored.revision,
            "instruction": "참고 그림체",
            "base_style": None,
            "use_reference": True,
        },
    )

    assert result["change_id"] is not None
    assert harness.templates.style_hints[-1] == StyleFrames(
        palette=["#112233"], frames=reference.sent
    )
