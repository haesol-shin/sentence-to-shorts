"""Activity time is stored per video and never makes a revision."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.plugins.registry import Registry
from app.ports import AppError
from app.schemas.api import (
    ActivityKind,
    ActivitySpan,
    CreateProjectRequest,
    CreateVideoRequest,
)
from app.schemas.common import Language
from app.services.project.service import ProjectService
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore
from app.storage.sqlite import Database


@pytest.fixture
def service(tmp_path: Path) -> Iterator[ProjectService]:
    layout = Layout(data=tmp_path / "data", cache=tmp_path / "cache")
    database = Database.open(layout.state_db)
    yield ProjectService(SqliteProjectStore(database, layout), Registry())
    database.close()


def span(kind: ActivityKind, start: int, end: int) -> ActivitySpan:
    return ActivitySpan(kind=kind, start_ms=start, end_ms=end)


def test_27_activity_adds_to_metrics_without_a_revision(service: ProjectService) -> None:
    project = service.create_project(CreateProjectRequest(title=None, language=Language.en))
    video = service.create_video(
        project.id, CreateVideoRequest(from_video_id=None, preset_id=None)
    )

    service.add_activity(
        video.id,
        [span(ActivityKind.active, 0, 1500), span(ActivityKind.waiting, 1500, 4000)],
    )
    service.add_activity(video.id, [span(ActivityKind.active, 5000, 5500)])

    metrics = service.projects.metrics(video.id)
    assert (metrics.active_ms, metrics.waiting_ms) == (2000, 2500)
    assert service.view(video.id) == video
    assert [info.revision for info in service.projects.list_revisions(video.id)] == [1]


def test_27_activity_rejects_reversed_spans_and_unknown_videos(service: ProjectService) -> None:
    project = service.create_project(CreateProjectRequest(title=None, language=Language.ko))
    video = service.create_video(
        project.id, CreateVideoRequest(from_video_id=None, preset_id=None)
    )

    with pytest.raises(AppError) as reversed_span:
        service.add_activity(video.id, [span(ActivityKind.active, 900, 100)])
    with pytest.raises(AppError) as unknown:
        service.add_activity(service.projects.new_id("v"), [span(ActivityKind.active, 0, 1)])

    assert reversed_span.value.code == "validation_failed"
    assert unknown.value.code == "not_found"
    assert service.projects.metrics(video.id).active_ms == 0
