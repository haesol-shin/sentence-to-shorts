"""User-visible change ranges and confirmations use the production key graph."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.plugins.registry import Registry
from app.ports import AppError, TtsEngineInfo
from app.schemas.api import CreateProjectRequest
from app.schemas.artifact import ArtifactKind
from app.schemas.change import ConfirmationReason, ReorderOp, SetOp, SetScriptOp, Target
from app.schemas.common import Language, Origin
from app.schemas.settings import LockKey, LockState
from app.schemas.video import ArtifactState, Video
from app.services.assemble.service import AssembleService
from app.services.pipeline.cache_keys import Graph, digest_bytes
from app.services.pipeline.dependencies import (
    build_view,
    plan_change,
    stale_wording_in_neighbors,
)
from app.services.pipeline.types import Services
from app.services.project.service import ProjectService
from app.services.voice.service import VoiceService
from app.storage.artifacts import FileArtifactStore
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore
from app.storage.sqlite import Database
from tests.conftest import load_json


class Engine:
    def info(self):
        return TtsEngineInfo("fixed_wav", digest_bytes(b"test engine"), 24000, ("ko", "en"))


class Aligner:
    def runtime_digest(self):
        return digest_bytes(b"test aligner")


@pytest.fixture
def change_context(tmp_path: Path):
    catalog = Registry()
    layout = Layout(data=tmp_path / "data", cache=tmp_path / "cache")
    database = Database.open(layout.state_db)
    store = SqliteProjectStore(database, layout)
    project = ProjectService(store, catalog)
    owner = project.create_project(CreateProjectRequest(title=None, language=Language.ko))
    video = Video.model_validate(load_json("contracts/valid/video_ko_just_three.json"))
    video.project_id = owner.id
    video.settings.visual.art_style = catalog.pin("art_style", "pixel")
    video.settings.format.layout = catalog.pin("template", "fixed_stage")
    video.settings.audio.voice = catalog.pin("voice", "fixed_wav")
    video.settings.audio.bgm.entry = catalog.pin("bgm", "builtin_loop")
    video.settings.caption.font_id = catalog.pin("font", "galmuri11")
    store.append_revision(video)
    artifacts = FileArtifactStore(database, layout)
    services = Services(
        project=project,
        story=None,
        reference=None,
        render=SimpleNamespace(artifacts=artifacts),
        voice=VoiceService(Engine(), Aligner(), artifacts),
        sound=None,
        assemble=AssembleService(None),
        templates=SimpleNamespace(
            sandbox=SimpleNamespace(runtime_digest=lambda: digest_bytes(b"test sandbox"))
        ),
    )
    yield video, services
    database.close()


def edit_line(video: Video, scene_id: str, field: str, text: str) -> SetOp:
    return SetOp(
        op="set", path=f"/scenes/{scene_id}/lines/0/{field}", value=text, origin=Origin.user
    )


def test_11_display_edit_reports_render_without_tts(change_context):
    video, services = change_context
    scene_id = video.scene_order[0]
    plan = plan_change(
        video, [edit_line(video, scene_id, "display_text", "새로운 화면 글")],
        "direct", Target(scene_id=scene_id, pointer=None), services,
    )
    assert plan.effects.scene_ids_text == [scene_id]
    assert plan.effects.scene_ids_tts == []
    assert plan.effects.scene_ids_render == [scene_id]
    assert ConfirmationReason.rebuild_render in plan.confirmation_reasons
    assert ConfirmationReason.rebuild_tts not in plan.confirmation_reasons
    assert services.project.view(video.id) == video


def test_11_spoken_edit_reports_only_its_scene(change_context):
    video, services = change_context
    scene_id = video.scene_order[1]
    plan = plan_change(
        video, [edit_line(video, scene_id, "speech_text", "새롭게 읽는 문장")],
        "chat", Target(scene_id=scene_id, pointer=None), services,
    )
    assert plan.effects.scene_ids_tts == [scene_id]
    assert plan.effects.scene_ids_render == [scene_id]
    assert plan.effects.mix and plan.effects.assemble
    assert ConfirmationReason.multi_scene not in plan.confirmation_reasons


def test_12_reorder_keeps_all_scene_ranges_empty(change_context):
    video, services = change_context
    plan = plan_change(
        video, [ReorderOp(op="reorder", order=list(reversed(video.scene_order)))],
        "direct", Target(scene_id=None, pointer=None), services,
    )
    assert plan.effects.scene_ids_text == []
    assert plan.effects.scene_ids_tts == []
    assert plan.effects.scene_ids_render == []
    assert plan.effects.assemble


def test_14_bgm_gain_changes_only_mix_and_assembly(change_context):
    video, services = change_context
    bgm = video.settings.audio.bgm.model_dump(mode="json")
    bgm["gain_db_x10"] = -180
    plan = plan_change(
        video, [SetOp(op="set", path="/settings/audio/bgm", value=bgm, origin=Origin.user)],
        "direct", Target(scene_id=None, pointer=None), services,
    )
    assert plan.effects.mix and plan.effects.assemble
    assert plan.effects.scene_ids_tts == []
    assert plan.effects.scene_ids_render == []


def test_26_single_unprotected_value_applies_without_confirmation(change_context):
    video, services = change_context
    plan = plan_change(
        video, [SetOp(op="set", path="/settings/format/humor", value="light", origin=Origin.user)],
        "chat", Target(scene_id=None, pointer=None), services,
    )
    assert not plan.requires_confirmation
    services.project.projects.put_change(plan)
    result = services.project.commit(plan, video.revision)
    assert result.settings.format.humor.value == "light"
    assert result.revision == video.revision + 1


def test_26_locked_and_user_owned_values_require_confirmation(change_context):
    video, services = change_context
    video.settings.locks[LockKey.humor] = LockState.locked
    video.settings.origins["/format/humor"] = Origin.user
    plan = plan_change(
        video, [SetOp(op="set", path="/settings/format/humor", value="light", origin=Origin.llm)],
        "card", Target(scene_id=None, pointer=None), services,
    )
    assert plan.effects.locked_keys == [LockKey.humor]
    assert plan.effects.overwrites_user_values == ["/settings/format/humor"]
    assert ConfirmationReason.lock_change in plan.confirmation_reasons
    assert ConfirmationReason.user_value_overwrite in plan.confirmation_reasons
    assert video.settings.format.humor.value == "none"


def test_26_chat_overwriting_user_value_requires_confirmation(change_context):
    video, services = change_context
    video.settings.origins["/format/humor"] = Origin.user
    plan = plan_change(
        video, [SetOp(op="set", path="/settings/format/humor", value="light", origin=Origin.user)],
        "chat", Target(scene_id=None, pointer=None), services,
    )
    assert plan.requires_confirmation
    assert plan.effects.overwrites_user_values == ["/settings/format/humor"]
    assert plan.confirmation_reasons == [ConfirmationReason.user_value_overwrite]


def test_26_whole_script_rewrite_requires_confirmation_even_with_same_content(change_context):
    video, services = change_context
    plan = plan_change(
        video,
        [SetScriptOp(
            op="set_script", script=video.script,
            scenes=[video.scenes[scene_id] for scene_id in video.scene_order],
        )],
        "chat", Target(scene_id=None, pointer=None), services,
    )
    assert plan.effects.script
    assert ConfirmationReason.script_rewrite in plan.confirmation_reasons


def test_26_multi_scene_change_requires_confirmation(change_context):
    video, services = change_context
    selected = video.scene_order[:2]
    plan = plan_change(
        video,
        [edit_line(video, scene_id, "display_text", "수정된 장면 글") for scene_id in selected],
        "chat", Target(scene_id=None, pointer=None), services,
    )
    assert plan.effects.scene_ids_render == selected
    assert ConfirmationReason.multi_scene in plan.confirmation_reasons


def test_26_confirmed_concept_change_is_rejected(change_context):
    video, services = change_context
    with pytest.raises(AppError, match="concept_locked"):
        plan_change(
            video, [SetOp(op="set", path="/settings/format/story_structure",
                          value="single_analogy", origin=Origin.user)],
            "chat", Target(scene_id=None, pointer=None), services,
        )


def test_26_neighbor_warning_preserves_untargeted_scene(change_context):
    video, _ = change_context
    first, neighbor = video.scene_order[:2]
    video.scenes[first].lines[0].display_text = "옛표현 설명"
    video.scenes[neighbor].lines[0].display_text = "옛표현 연결"
    changed = video.model_copy(deep=True)
    changed.scenes[first].lines[0].display_text = "새표현 설명"
    warnings = stale_wording_in_neighbors(video, changed)
    assert [warning.scene_id for warning in warnings] == [neighbor]
    assert changed.scenes[neighbor] == video.scenes[neighbor]


def test_26_build_view_resolves_current_keys_and_length(change_context, tmp_path):
    video, services = change_context
    scene_id = video.scene_order[0]
    key = Graph(video, services).scenes[scene_id].still
    path = tmp_path / "still.png"
    Image.new("RGB", (540, 960)).save(path)
    artifact = services.artifact_store.publish(
        ArtifactKind.still_png, key, path, {"width": 540, "height": 960}, None
    )
    view = build_view(video, services)
    assert view.scenes[scene_id].still.state is ArtifactState.fresh
    assert view.scenes[scene_id].still.artifact.id == artifact.id
    assert view.scenes[scene_id].still.artifact.digest == artifact.digest
    assert view.estimated_ms == sum(
        services.voice.estimate_ms(line, video.settings.language.value)
        for scene in video.scenes.values() for line in scene.lines
    )
    assert view.actual_ms is None
    assert view.final.state is ArtifactState.missing


def test_26_build_view_never_calls_old_key_fresh(change_context, tmp_path):
    video, services = change_context
    scene_id = video.scene_order[0]
    key = Graph(video, services).scenes[scene_id].still
    path = tmp_path / "still.png"
    Image.new("RGB", (540, 960)).save(path)
    artifact = services.artifact_store.publish(ArtifactKind.still_png, key, path, {}, None)
    services.previous_keys[(video.id, "still_png", scene_id, None)] = key
    changed = video.model_copy(deep=True)
    changed.scenes[scene_id].lines[0].display_text = "바뀐 화면 글"
    view = build_view(changed, services)
    assert view.scenes[scene_id].still.state is ArtifactState.stale
    assert view.scenes[scene_id].still.artifact.id == artifact.id
    assert view.scenes[scene_id].still.cache_key != key


def test_26_build_view_observations_are_revision_and_key_scoped(change_context):
    video, services = change_context
    scene_id = video.scene_order[0]
    key = Graph(video, services).scenes[scene_id].clip
    identity = (video.id, video.revision, "clip_mp4", scene_id, None)
    services.build_states[identity] = {"state": "building", "cache_key": key}
    assert build_view(video, services).scenes[scene_id].clip.state is ArtifactState.building
    services.build_states[identity] = {
        "state": "failed", "cache_key": key, "error_code": "render_failed"
    }
    failed = build_view(video, services).scenes[scene_id].clip
    assert failed.state is ArtifactState.failed
    assert failed.error_code == "render_failed"
    changed = video.model_copy(deep=True)
    changed.scenes[scene_id].lines[0].display_text = "새 key"
    assert build_view(changed, services).scenes[scene_id].clip.state is ArtifactState.missing
    later = video.model_copy(update={"revision": video.revision + 1})
    assert build_view(later, services).scenes[scene_id].clip.state is ArtifactState.missing
