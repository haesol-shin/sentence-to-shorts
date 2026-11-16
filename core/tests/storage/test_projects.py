"""ProjectStore: immutable revisions, head + 1 appends, roots with Korean and spaces."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.ports import AppError
from app.schemas.api import ActivityKind, ActivitySpan
from app.schemas.change import ChangePlan
from app.schemas.preset import Preset
from app.storage.paths import Layout, resolve_roots
from app.storage.projects import RevisionConflict, SqliteProjectStore
from app.storage.sqlite import Database
from tests.conftest import load_json
from tests.storage.conftest import next_revision


def test_korean_space_root_round_trips_documents(tmp_path: Path, project, video) -> None:
    env = {
        "APP_DATA_DIR": str(tmp_path / "데이터 폴더" / "앱 data"),
        "APP_CACHE_DIR": str(tmp_path / "캐시 폴더"),
    }
    roots = resolve_roots("app", env=env, home=tmp_path / "home")
    layout = Layout(data=roots.data, cache=roots.cache)
    database = Database.open(layout.state_db)
    try:
        store = SqliteProjectStore(database, layout)
        store.put_project(project)
        store.append_revision(video)
        assert store.get_project(project.id) == project
        assert store.get_video(video.id) == video
    finally:
        database.close()
    assert layout.state_db.is_file()
    assert layout.revision_file(project.id, video.id, 1).is_file()
    assert str(layout.state_db).startswith(env["APP_DATA_DIR"])


def test_past_revision_bytes_unchanged_after_later_writes(
    projects: SqliteProjectStore, layout: Layout, project, video
) -> None:
    projects.put_project(project)
    projects.append_revision(video)
    first = layout.revision_file(project.id, video.id, 1)
    before = (first.read_bytes(), first.stat().st_mtime_ns)

    second = next_revision(video).model_copy(update={"topic": "다른 주제"})
    projects.append_revision(second)
    for stale in (video, second):
        with pytest.raises(RevisionConflict):
            projects.append_revision(stale)
    projects.put_project(project.model_copy(update={"title": "새 제목"}))

    assert (first.read_bytes(), first.stat().st_mtime_ns) == before
    assert projects.get_video(video.id, 1) == video
    assert projects.get_video(video.id) == second
    assert [info.revision for info in projects.list_revisions(video.id)] == [1, 2]


def test_revision_conflict_unless_head_plus_one(
    projects: SqliteProjectStore, layout: Layout, project, video
) -> None:
    projects.put_project(project)
    with pytest.raises(RevisionConflict) as missing:
        projects.append_revision(next_revision(video))
    assert missing.value.code == "revision_conflict"
    assert missing.value.current_revision is None

    projects.append_revision(video)
    skipped = next_revision(next_revision(video))
    with pytest.raises(RevisionConflict) as ahead:
        projects.append_revision(skipped)
    assert ahead.value.detail == {"current_revision": 1}
    assert not layout.revision_file(project.id, video.id, 3).exists()
    assert projects.get_video(video.id).revision == 1


def test_revision_newer_document_is_refused(
    projects: SqliteProjectStore, layout: Layout, project, video
) -> None:
    projects.put_project(project)
    projects.append_revision(video)
    path = layout.revision_file(project.id, video.id, 1)
    path.write_bytes(path.read_bytes().replace(b'"schema_version":2', b'"schema_version":3'))
    with pytest.raises(AppError) as refused:
        projects.get_video(video.id)
    assert refused.value.code == "unsupported_version"
    assert refused.value.detail == {"found": 3, "supported": 2}


def test_revision_newer_project_is_refused(
    projects: SqliteProjectStore, layout: Layout, project
) -> None:
    projects.put_project(project)
    path = layout.project_file(project.id)
    path.write_bytes(path.read_bytes().replace(b'"schema_version":1', b'"schema_version":2'))
    for read in (
        lambda: projects.get_project(project.id),
        lambda: projects.list_projects(project.owner_id),
    ):
        with pytest.raises(AppError) as refused:
            read()
        assert refused.value.code == "unsupported_version"
        assert refused.value.detail == {"found": 2, "supported": 1}


@pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0, reason="needs POSIX directory permissions"
)
def test_project_delete_reports_file_error_and_retries(
    projects: SqliteProjectStore, layout: Layout, project, video
) -> None:
    projects.put_project(project)
    projects.append_revision(video)
    project_dir = layout.project_dir(project.id)
    project_dir.chmod(0o500)
    try:
        with pytest.raises(OSError):
            projects.delete_project(project.id)
    finally:
        project_dir.chmod(0o700)
    assert layout.project_file(project.id).exists()
    with pytest.raises(AppError):
        projects.get_project(project.id)

    projects.delete_project(project.id)
    assert not project_dir.exists()
    with pytest.raises(AppError) as gone:
        projects.delete_project(project.id)
    assert gone.value.code == "not_found"



def test_project_delete_removes_only_that_project(
    projects: SqliteProjectStore, layout: Layout, project, video
) -> None:
    other = project.model_copy(update={"id": projects.new_id("p")})
    projects.put_project(project)
    projects.put_project(other)
    projects.append_revision(video)
    projects.put_preset(Preset.model_validate(load_json("contracts/valid/preset_min.json")))
    projects.put_change(
        ChangePlan.model_validate(load_json("contracts/valid/change_single_value.json"))
    )

    projects.delete_project(project.id)

    assert not layout.project_dir(project.id).exists()
    assert [item.id for item in projects.list_projects(project.owner_id)] == [other.id]
    for lookup in (
        lambda: projects.get_project(project.id),
        lambda: projects.get_video(video.id),
        lambda: projects.list_presets(project.id),
        lambda: projects.get_change("c_0t2wvk16pb9s0a453j9s6540mg"),
    ):
        with pytest.raises(AppError) as gone:
            lookup()
        assert gone.value.code == "not_found"


def test_activity_metrics_sum_spans_by_kind(
    projects: SqliteProjectStore, project, video
) -> None:
    projects.put_project(project)
    projects.append_revision(video)
    projects.add_activity(
        video.id,
        [
            ActivitySpan(kind=ActivityKind.active, start_ms=0, end_ms=1500),
            ActivitySpan(kind=ActivityKind.waiting, start_ms=1500, end_ms=4000),
            ActivitySpan(kind=ActivityKind.active, start_ms=4000, end_ms=4500),
        ],
    )
    metrics = projects.metrics(video.id)
    assert (metrics.active_ms, metrics.waiting_ms) == (2000, 2500)
