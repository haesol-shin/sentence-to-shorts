"""Stage gates: concept, script and scene confirmation (CONTRACTS 4.1)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.plugins.registry import Registry
from app.ports import AppError
from app.schemas.api import CreateProjectRequest, CreateVideoRequest
from app.schemas.change import (
    ChangePlan,
    ChangeSource,
    ChangeStatus,
    Effects,
    Op,
    ReplaceSceneOp,
    SetOp,
    SetScriptOp,
    Target,
)
from app.schemas.common import Language, Origin
from app.schemas.scene import Scene
from app.schemas.script import Script
from app.schemas.video import Video, VideoStage
from app.services.project.service import ProjectService
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore
from app.storage.sqlite import Database
from tests.conftest import load_json

TOPIC = SetOp(op="set", path="/topic", value="합성 주제", origin=Origin.user)


@pytest.fixture(scope="module")
def catalog() -> Registry:
    return Registry()


@pytest.fixture
def service(tmp_path: Path, catalog: Registry) -> Iterator[ProjectService]:
    layout = Layout(data=tmp_path / "data", cache=tmp_path / "cache")
    database = Database.open(layout.state_db)
    yield ProjectService(SqliteProjectStore(database, layout), catalog)
    database.close()


def new_video(service: ProjectService) -> Video:
    project = service.create_project(CreateProjectRequest(title=None, language=Language.ko))
    return service.create_video(project.id, CreateVideoRequest(from_video_id=None, preset_id=None))


def fixture_scenes() -> list[Scene]:
    video = Video.model_validate(load_json("contracts/valid/video_ko_just_three.json"))
    return [video.scenes[scene_id] for scene_id in video.scene_order]


def commit(
    service: ProjectService,
    video: Video,
    ops: list[Op],
    source: ChangeSource = ChangeSource.direct,
) -> Video:
    change = ChangePlan(
        schema_version=2,
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
            locked_keys=[],
            overwrites_user_values=[],
        ),
        requires_confirmation=False,
        confirmation_reasons=[],
        warnings=[],
        unsupported=[],
        notes=[],
        status=ChangeStatus.proposed,
        applied_revision=None,
    )
    service.projects.put_change(change)
    return service.commit(change, video.revision)


def write_script(service: ProjectService, video: Video, *, visual: bool) -> Video:
    scenes = [
        scene if visual else scene.model_copy(update={"visual": None})
        for scene in fixture_scenes()
    ]
    script = Script(source="llm", raw_text=None, title=None)
    return commit(service, video, [SetScriptOp(op="set_script", script=script, scenes=scenes)])


def code_of(call) -> str:  # type: ignore[no-untyped-def]
    with pytest.raises(AppError) as error:
        call()
    return error.value.code


def test_2_script_confirm_requires_a_script(service: ProjectService) -> None:
    video = new_video(service)
    assert code_of(lambda: service.confirm_script(video.id, 1)) == "script_missing"


def test_2_scenes_confirm_requires_a_confirmed_script(service: ProjectService) -> None:
    video = write_script(service, new_video(service), visual=True)
    assert code_of(lambda: service.confirm_scenes(video.id, 2)) == "script_not_confirmed"
    assert service.view(video.id).stage is VideoStage.draft


def test_2_scenes_confirm_requires_scene_visuals(service: ProjectService) -> None:
    video = write_script(service, new_video(service), visual=False)
    confirmed = service.confirm_script(video.id, 2)
    assert confirmed.stage is VideoStage.script_confirmed
    assert code_of(lambda: service.confirm_scenes(video.id, 3)) == "scene_data_missing"

    filled = commit(
        service,
        confirmed,
        [ReplaceSceneOp(op="replace_scene", scene=scene) for scene in fixture_scenes()],
    )
    assert filled.stage is VideoStage.script_confirmed

    done = service.confirm_scenes(video.id, filled.revision)
    assert done.stage is VideoStage.scenes_confirmed
    assert service.confirm_scenes(video.id, done.revision) == done


def test_2_confirmations_never_move_the_stage_back(service: ProjectService) -> None:
    video = write_script(service, new_video(service), visual=True)
    scenes = service.confirm_scenes(
        video.id, service.confirm_script(video.id, 2).revision
    )
    assert service.confirm_script(video.id, scenes.revision) == scenes
    assert service.confirm_concept(video.id, scenes.revision) == scenes
    assert service.view(video.id).revision == scenes.revision


def test_4_confirmed_concept_refuses_concept_changes(service: ProjectService) -> None:
    video = new_video(service)
    assert code_of(lambda: service.confirm_concept(video.id, 1)) == "concept_missing"
    topic = commit(service, video, [TOPIC])
    concept = service.confirm_concept(video.id, topic.revision)
    assert concept.stage is VideoStage.concept_confirmed

    change = SetOp(
        op="set",
        path="/settings/format/story_structure",
        value="single_analogy",
        origin=Origin.user,
    )
    assert code_of(lambda: commit(service, concept, [change])) == "concept_locked"
    humor = SetOp(op="set", path="/settings/format/humor", value="light", origin=Origin.user)
    assert commit(service, concept, [humor]).settings.format.humor.value == "light"


def test_4_confirmed_concept_refuses_a_locked_concept_change(service: ProjectService) -> None:
    video = new_video(service)
    locks = {key.value: value.value for key, value in video.settings.locks.items()}
    lock = SetOp(
        op="set",
        path="/settings/locks",
        value={**locks, "story_structure": "locked"},
        origin=Origin.user,
    )
    ready = commit(service, video, [TOPIC, lock])
    concept = service.confirm_concept(video.id, ready.revision)
    change = SetOp(
        op="set",
        path="/settings/format/story_structure",
        value="single_analogy",
        origin=Origin.user,
    )

    assert code_of(lambda: commit(service, concept, [change])) == "concept_locked"
    assert service.view(video.id).revision == concept.revision


@pytest.mark.parametrize("source", [ChangeSource.card, ChangeSource.reference])
def test_4_confirmed_concept_refuses_a_lower_origin_concept_change(
    service: ProjectService, source: ChangeSource
) -> None:
    video = new_video(service)
    picked = SetOp(
        op="set",
        path="/settings/format/story_structure",
        value="numbered_three",
        origin=Origin.user,
    )
    ready = commit(service, video, [TOPIC, picked])
    assert ready.settings.origins["/format/story_structure"] is Origin.user
    concept = service.confirm_concept(video.id, ready.revision)
    change = picked.model_copy(update={"value": "single_analogy", "origin": Origin.card})

    assert code_of(lambda: commit(service, concept, [change], source)) == "concept_locked"
    assert service.view(video.id).revision == concept.revision


def test_4_confirmed_concept_refuses_a_change_hidden_by_a_later_lower_write(
    service: ProjectService,
) -> None:
    video = new_video(service)
    concept = service.confirm_concept(video.id, commit(service, video, [TOPIC]).revision)
    pointer = "/settings/format/story_structure"
    first = SetOp(op="set", path=pointer, value="single_analogy", origin=Origin.user)
    back = SetOp(op="set", path=pointer, value="numbered_three", origin=Origin.card)

    for ops in ([first, back], [first]):
        refused = code_of(lambda: commit(service, concept, ops, ChangeSource.chat))
        assert refused == "concept_locked"
    head = service.view(video.id)
    assert head.revision == concept.revision
    assert head.settings.format.story_structure == "numbered_three"



def test_26_script_rewrite_after_scene_confirmation_keeps_the_concept(
    service: ProjectService,
) -> None:
    video = new_video(service)
    topic = commit(service, video, [TOPIC])
    service.confirm_concept(video.id, topic.revision)
    scripted = write_script(service, service.view(video.id), visual=True)
    scenes = service.confirm_scenes(
        video.id, service.confirm_script(video.id, scripted.revision).revision
    )
    assert scenes.stage is VideoStage.scenes_confirmed

    rewritten = write_script(service, scenes, visual=True)

    assert rewritten.stage is VideoStage.concept_confirmed
