"""Commit, stale plans, undo and persistence across service instances."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from app.plugins.registry import Registry
from app.ports import AppError
from app.schemas.api import BaseRevision, CreateProjectRequest, CreateVideoRequest
from app.schemas.change import (
    ChangePlan,
    ChangeSource,
    ChangeStatus,
    ConfirmationReason,
    Effects,
    Op,
    SetOp,
    SetScriptOp,
    Target,
)
from app.schemas.common import Language, Origin
from app.schemas.project import Project
from app.schemas.script import Script
from app.schemas.settings import LockKey, LockState
from app.schemas.video import CreatedBy, Video
from app.services.project import revision, state
from app.services.project.service import ProjectService
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore
from app.storage.sqlite import Database
from tests.conftest import load_json

DEFAULT_LOCKS = {key.value: value.value for key, value in state.DEFAULT_LOCKS.items()}


@pytest.fixture(scope="module")
def catalog() -> Registry:
    return Registry()


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    return Layout(data=tmp_path / "data", cache=tmp_path / "cache")


@pytest.fixture
def service(layout: Layout, catalog: Registry) -> Iterator[ProjectService]:
    database = Database.open(layout.state_db)
    yield ProjectService(SqliteProjectStore(database, layout), catalog)
    database.close()


def new_video(service: ProjectService) -> Video:
    project = service.create_project(CreateProjectRequest(title=None, language=Language.ko))
    return service.create_video(project.id, CreateVideoRequest(from_video_id=None, preset_id=None))


def set_op(path: str, value: Any, origin: Origin = Origin.user) -> SetOp:
    return SetOp(op="set", path=path, value=value, origin=origin)


def plan(
    service: ProjectService,
    video: Video,
    ops: list[Op],
    *,
    source: ChangeSource = ChangeSource.direct,
    reasons: list[ConfirmationReason] | None = None,
    locked: list[LockKey] | None = None,
    overwrites: list[str] | None = None,
) -> ChangePlan:
    change = ChangePlan(
        schema_version=1,
        id=service.projects.new_id("c"),
        video_id=video.id,
        base_revision=video.revision,
        created_at=datetime.now(UTC),
        source=source,
        target=Target(scene_id=None, pointer=None),
        ops=ops,
        effects=Effects(
            script=False,
            scene_ids_text=[],
            scene_ids_tts=[],
            scene_ids_render=[],
            mix=False,
            assemble=False,
            locked_keys=locked or [],
            overwrites_user_values=overwrites or [],
        ),
        requires_confirmation=bool(reasons),
        confirmation_reasons=reasons or [],
        warnings=[],
        unsupported=[],
        notes=[],
        status=ChangeStatus.proposed,
        applied_revision=None,
    )
    service.projects.put_change(change)
    return change


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_26_commit_writes_the_next_revision_and_marks_the_plan(service: ProjectService) -> None:
    video = new_video(service)
    change = plan(service, video, [set_op("/topic", "합성 주제")])

    committed = service.commit(change, base_revision=1)

    assert (committed.revision, committed.parent_revision) == (2, 1)
    assert (committed.created_by, committed.change_id, committed.topic) == (
        CreatedBy.change,
        change.id,
        "합성 주제",
    )
    stored = service.projects.get_change(change.id)
    assert (stored.status, stored.applied_revision) == (ChangeStatus.applied, 2)
    assert service.commit(stored, base_revision=1) == committed
    assert len(service.projects.list_revisions(video.id)) == 2


def test_26_proposed_plan_goes_stale_when_the_head_moves(service: ProjectService) -> None:
    video = new_video(service)
    first = plan(service, video, [set_op("/topic", "첫 주제")])
    second = plan(service, video, [set_op("/topic", "둘째 주제")])
    third = plan(service, video, [set_op("/topic", "셋째 주제")])
    service.commit(first, base_revision=1)

    assert service.projects.get_change(second.id).status is ChangeStatus.stale
    assert service.projects.get_change(third.id).status is ChangeStatus.stale
    with pytest.raises(AppError) as error:
        service.commit(second, base_revision=2)
    assert error.value.code == "change_stale"

    later = plan(service, service.view(video.id), [set_op("/topic", "넷째 주제")])
    service.undo(video.id, base_revision=2)
    assert service.projects.get_change(later.id).status is ChangeStatus.stale


def test_26_retry_after_lost_plan_status_returns_the_written_revision(
    layout: Layout, catalog: Registry
) -> None:
    database = Database.open(layout.state_db)
    first = ProjectService(SqliteProjectStore(database, layout), catalog)
    video = new_video(first)
    change = plan(first, video, [set_op("/topic", "합성 주제")])
    committed = first.commit(change, base_revision=1)
    first.projects.put_change(change)  # the applied status write was lost
    database.close()

    reopened_db = Database.open(layout.state_db)
    try:
        reopened = ProjectService(SqliteProjectStore(reopened_db, layout), catalog)
        assert reopened.commit(change, base_revision=1) == committed
        stored = reopened.projects.get_change(change.id)
        assert (stored.status, stored.applied_revision) == (ChangeStatus.applied, 2)
        assert len(reopened.projects.list_revisions(video.id)) == 2
    finally:
        reopened_db.close()


def test_26_retry_after_lost_status_and_a_later_change_still_succeeds(
    layout: Layout, catalog: Registry
) -> None:
    database = Database.open(layout.state_db)
    first = ProjectService(SqliteProjectStore(database, layout), catalog)
    video = new_video(first)
    lost = plan(first, video, [set_op("/topic", "합성 주제")])
    committed = first.commit(lost, base_revision=1)
    first.projects.put_change(lost.model_copy(update={"status": ChangeStatus.stale}))
    later = plan(first, committed, [set_op("/settings/format/humor", "light")])
    first.commit(later, base_revision=2)
    database.close()

    reopened_db = Database.open(layout.state_db)
    try:
        reopened = ProjectService(SqliteProjectStore(reopened_db, layout), catalog)
        stored = reopened.projects.get_change(lost.id)
        assert (stored.status, stored.applied_revision) == (ChangeStatus.applied, 2)
        assert reopened.commit(lost, base_revision=3) == committed
        assert len(reopened.projects.list_revisions(video.id)) == 3
    finally:
        reopened_db.close()


class ConcurrentProposalStore(SqliteProjectStore):
    """Stores a plan made at the new head right after each revision write, the
    way a second request would between the write and the expiry of old plans."""

    make: Any = None
    made: list[ChangePlan] = []

    def append_revision(self, video: Video) -> Video:
        written = super().append_revision(video)
        if self.make is not None:
            self.made.append(self.make(written))
        return written


def test_26_plan_made_at_the_new_head_is_not_expired(
    layout: Layout, catalog: Registry
) -> None:
    database = Database.open(layout.state_db)
    try:
        store = ConcurrentProposalStore(database, layout)
        service = ProjectService(store, catalog)
        video = new_video(service)
        old = plan(service, video, [set_op("/topic", "옛 제안")])
        store.made = []
        store.make = lambda head: plan(service, head, [set_op("/topic", "새 제안")])
        service.commit(plan(service, video, [set_op("/topic", "합성 주제")]), base_revision=1)
        store.make = None

        assert service.projects.get_change(old.id).status is ChangeStatus.stale
        fresh = service.projects.get_change(store.made[0].id)
        assert (fresh.base_revision, fresh.status) == (2, ChangeStatus.proposed)
        assert service.commit(fresh, base_revision=2).topic == "새 제안"
    finally:
        database.close()


def test_8_cleared_then_refilled_visual_across_plans_keeps_a_locked_background(
    layout: Layout, catalog: Registry
) -> None:
    scenes = [
        Video.model_validate(load_json("contracts/valid/video_ko_just_three.json")).scenes[sid]
        for sid in load_json("contracts/valid/video_ko_just_three.json")["scene_order"]
    ]
    database = Database.open(layout.state_db)
    first = ProjectService(SqliteProjectStore(database, layout), catalog)
    video = new_video(first)
    script = Script(source="llm", raw_text=None, title=None)
    ready = first.commit(
        plan(
            first,
            video,
            [
                SetScriptOp(op="set_script", script=script, scenes=scenes),
                set_op("/settings/locks", {**DEFAULT_LOCKS, "background": "locked"}),
            ],
        ),
        base_revision=1,
    )
    scene_id = ready.scene_order[0]
    visual = ready.scenes[scene_id].visual
    assert visual is not None and visual.background_id == "bg_village"
    pointer = f"/scenes/{scene_id}/visual"
    cleared = first.commit(
        plan(first, ready, [set_op(pointer, None)], source=ChangeSource.chat), base_revision=2
    )
    other = visual.model_dump(mode="json") | {"background_id": "bg_stars"}
    first.commit(
        plan(first, cleared, [set_op(pointer, other)], source=ChangeSource.chat),
        base_revision=3,
    )
    database.close()

    reopened_db = Database.open(layout.state_db)
    try:
        head = ProjectService(SqliteProjectStore(reopened_db, layout), catalog).view(video.id)
        kept = head.scenes[scene_id].visual
        assert kept is not None and kept.background_id == "bg_village"
    finally:
        reopened_db.close()



def test_4_commit_refuses_a_different_invalid_value_at_an_old_issue(
    service: ProjectService,
) -> None:
    video = new_video(service)
    fmt = video.settings.format.model_copy(update={"story_structure": "missing_one"})
    broken = service.projects.append_revision(
        revision.next_revision(
            video.model_copy(
                update={"settings": video.settings.model_copy(update={"format": fmt})}
            ),
            video,
            CreatedBy.system,
        )
    )
    assert service.validate(broken) != []

    other = plan(service, broken, [set_op("/settings/format/story_structure", "missing_two")])
    with pytest.raises(AppError) as error:
        service.commit(other, base_revision=2)
    assert error.value.code == "invalid_combination"

    humor = plan(service, broken, [set_op("/settings/format/humor", "light")])
    assert service.commit(humor, base_revision=2).settings.format.humor.value == "light"


def test_4_semantic_fixture_stale_base_revision_conflicts(service: ProjectService) -> None:
    expected = load_json("contracts/invalid/expect.json")["files"][
        "stale_base_revision_request.json"
    ]["code"]
    stale = BaseRevision.model_validate(
        load_json("contracts/invalid/stale_base_revision_request.json")
    )
    video = new_video(service)
    service.commit(plan(service, video, [set_op("/topic", "합성 주제")]), base_revision=1)
    head = service.view(video.id)

    calls = [
        lambda: service.undo(video.id, stale.base_revision),
        lambda: service.confirm_script(video.id, stale.base_revision),
        lambda: service.commit(plan(service, head, [set_op("/topic", "x")]), stale.base_revision),
    ]
    for call in calls:
        with pytest.raises(AppError) as error:
            call()
        assert error.value.code == expected
        assert error.value.detail == {"current_revision": 2}
    assert service.view(video.id) == head


def test_9a_past_revision_files_keep_their_hash(
    service: ProjectService, layout: Layout
) -> None:
    video = new_video(service)
    first = layout.revision_file(video.project_id, video.id, 1)
    before = sha256(first)

    service.commit(plan(service, video, [set_op("/topic", "합성 주제")]), base_revision=1)
    second = layout.revision_file(video.project_id, video.id, 2)
    second_hash = sha256(second)
    undone = service.undo(video.id, base_revision=2)
    service.commit(plan(service, undone, [set_op("/topic", "새 주제")]), base_revision=3)
    service.confirm_concept(video.id, base_revision=4)

    assert sha256(first) == before
    assert sha256(second) == second_hash
    revisions = [info.revision for info in service.projects.list_revisions(video.id)]
    assert revisions == [1, 2, 3, 4, 5]


def test_26_undo_restores_the_previous_revision(service: ProjectService) -> None:
    video = new_video(service)
    with pytest.raises(AppError) as first:
        service.undo(video.id, base_revision=1)
    assert first.value.code == "nothing_to_undo"
    service.commit(plan(service, video, [set_op("/topic", "합성 주제")]), base_revision=1)

    undone = service.undo(video.id, base_revision=2)

    assert (undone.revision, undone.parent_revision, undone.created_by) == (
        3,
        2,
        CreatedBy.undo,
    )
    assert revision.content(undone) == revision.content(service.projects.get_video(video.id, 1))
    with pytest.raises(AppError) as again:
        service.undo(video.id, base_revision=3)
    assert again.value.code == "nothing_to_undo"


def test_8_commit_changes_a_locked_item_only_with_lock_confirmation(
    service: ProjectService,
) -> None:
    video = service.commit(
        plan(
            service,
            new_video(service),
            [set_op("/settings/locks", {**DEFAULT_LOCKS, "humor": "locked"})],
        ),
        base_revision=1,
    )
    change = [set_op("/settings/format/humor", "light")]

    kept = service.commit(plan(service, video, change), base_revision=2)
    assert kept.settings.format.humor.value == "none"

    confirmed = service.commit(
        plan(
            service,
            kept,
            change,
            reasons=[ConfirmationReason.lock_change],
            locked=[LockKey.humor],
        ),
        base_revision=3,
    )
    assert confirmed.settings.format.humor.value == "light"


def test_5_card_plan_keeps_user_value_unless_confirmed(service: ProjectService) -> None:
    video = service.commit(
        plan(service, new_video(service), [set_op("/settings/format/humor", "light")]),
        base_revision=1,
    )
    card = [set_op("/settings/format/humor", "none", Origin.user)]

    kept = service.commit(plan(service, video, card, source=ChangeSource.card), base_revision=2)
    assert kept.settings.format.humor.value == "light"

    overwritten = service.commit(
        plan(
            service,
            kept,
            card,
            source=ChangeSource.card,
            reasons=[ConfirmationReason.user_value_overwrite],
            overwrites=["/settings/format/humor"],
        ),
        base_revision=3,
    )
    assert overwritten.settings.format.humor.value == "none"
    assert overwritten.settings.origins["/format/humor"] is Origin.card


def test_4_commit_refuses_a_new_invalid_combination(service: ProjectService) -> None:
    video = new_video(service)
    change = plan(service, video, [set_op("/settings/caption/mode", "typewriter")])

    with pytest.raises(AppError) as error:
        service.commit(change, base_revision=1)

    assert error.value.code == "invalid_combination"
    assert service.view(video.id).revision == 1


def test_9a_video_change_keeps_project_defaults(service: ProjectService) -> None:
    video = new_video(service)
    project = service.projects.get_project(video.project_id)
    service.commit(
        plan(service, video, [set_op("/settings/format/humor", "light")]), base_revision=1
    )

    assert service.projects.get_project(project.id).defaults == project.defaults
    later = service.create_video(
        project.id, CreateVideoRequest(from_video_id=None, preset_id=None)
    )
    assert later.settings.format.humor.value == "none"


def test_9_videos_of_a_project_share_the_default_voice(service: ProjectService) -> None:
    video = new_video(service)
    other = service.create_video(
        video.project_id, CreateVideoRequest(from_video_id=None, preset_id=None)
    )
    assert other.settings.audio.voice == video.settings.audio.voice
    assert video.settings.locks[LockKey.voice].value == "locked"


def test_9a_reopened_service_keeps_user_values_and_locks(
    layout: Layout, catalog: Registry
) -> None:
    database = Database.open(layout.state_db)
    first = ProjectService(SqliteProjectStore(database, layout), catalog)
    video = new_video(first)
    edited = first.commit(
        plan(
            first,
            video,
            [
                set_op("/settings/format/register", "casual"),
                set_op("/settings/locks", {**DEFAULT_LOCKS, "register": "locked"}),
            ],
        ),
        base_revision=1,
    )
    database.close()

    reopened_db = Database.open(layout.state_db)
    try:
        reopened = ProjectService(SqliteProjectStore(reopened_db, layout), catalog)
        head = reopened.view(video.id)
        assert head == edited
        assert head.settings.format.register_value.value == "casual"
        assert head.settings.origins["/format/register"] is Origin.user
        assert head.settings.locks == {**state.DEFAULT_LOCKS, LockKey.register: LockState.locked}
        model = reopened.apply_ops(
            head, [set_op("/settings/format/register", "neutral", Origin.llm)], Origin.llm
        )
        assert model.settings.format.register_value.value == "casual"
    finally:
        reopened_db.close()


def test_9a_concurrent_creation_keeps_both_videos_after_restart(
    layout: Layout, catalog: Registry
) -> None:
    barrier = Barrier(2)

    class SynchronizedStore(SqliteProjectStore):
        def get_project(self, project_id: str) -> Project:
            project = super().get_project(project_id)
            barrier.wait(timeout=10)
            return project

    first_db = Database.open(layout.state_db)
    second_db = Database.open(layout.state_db)
    try:
        initial = ProjectService(SqliteProjectStore(first_db, layout), catalog)
        existing = new_video(initial)
        project = initial.projects.get_project(existing.project_id)
        services = [
            ProjectService(SynchronizedStore(database, layout), catalog)
            for database in (first_db, second_db)
        ]
        req = CreateVideoRequest(from_video_id=None, preset_id=None)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(service.create_video, project.id, req)
                for service in services
            ]
            created = [future.result(timeout=20) for future in futures]
        expected = {existing.id, *(video.id for video in created)}
        stored = initial.projects.get_project(project.id)
        assert len(stored.video_ids) == 3
        assert set(stored.video_ids) == expected
        assert stored.defaults == project.defaults
    finally:
        second_db.close()
        first_db.close()

    reopened_db = Database.open(layout.state_db)
    try:
        reopened = SqliteProjectStore(reopened_db, layout)
        listed = reopened.list_projects(project.owner_id)
        assert len(listed) == 1
        assert set(listed[0].video_ids) == expected
        for video in (existing, *created):
            assert reopened.get_video(video.id) == video
    finally:
        reopened_db.close()
