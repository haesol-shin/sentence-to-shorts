"""Next-video continuity, catalog variation and immutable revision-one creation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.plugins.registry import Registry
from app.ports import AppError
from app.schemas.api import CreateProjectRequest, CreateVideoRequest
from app.schemas.change import ConfirmationReason
from app.schemas.common import CharacterRole, Language, Origin
from app.schemas.settings import Humor, LockKey, LockState
from app.schemas.video import CreatedBy, Video, VideoStage
from app.services.project import derive
from app.services.project.service import ProjectService
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore, new_typeid
from app.storage.sqlite import Database
from tests.conftest import load_json
from tests.fixtures.media import tone_wav
from tests.project.test_revision import plan, set_op


@pytest.fixture
def service(tmp_path: Path) -> Iterator[ProjectService]:
    layout = Layout(data=tmp_path / "data", cache=tmp_path / "cache")
    database = Database.open(layout.state_db)
    yield ProjectService(SqliteProjectStore(database, layout), Registry(data_dir=layout.data))
    database.close()


def project_video(service: ProjectService) -> Video:
    project = service.create_project(CreateProjectRequest(title=None, language=Language.ko))
    return service.create_video(project.id, CreateVideoRequest(from_video_id=None, preset_id=None))


def next_video(service: ProjectService, source: Video) -> Video:
    return service.create_video(
        source.project_id, CreateVideoRequest(from_video_id=source.id, preset_id=None)
    )


def test_9a_next_video_clears_content_and_keeps_locked_snapshot(
    service: ProjectService, tmp_path: Path,
) -> None:
    first = project_video(service)
    doc = load_json("contracts/valid/video_ko_just_three.json")
    doc.update(
        id=service.projects.new_id("v"), project_id=first.project_id,
        settings=first.settings.model_dump(mode="json", by_alias=True),
        material=[{"id": service.projects.new_id("m"), "text": "Synthetic material"}],
        reference={
            "id": service.projects.new_id("r"), "kind": "file", "host": None,
            "status": "analyzed", "source_deleted": True, "measured": None, "style": None,
        },
    )
    source = Video.model_validate(doc)
    source.settings.format.humor = Humor.light
    source.settings.origins["/format/humor"] = Origin.user
    source.settings.locks[LockKey.humor] = LockState.locked
    service.projects.append_revision(source)
    layout = Layout(data=tmp_path / "data", cache=tmp_path / "cache")
    old_path = layout.revision_file(source.project_id, source.id, 1)
    old_hash = hashlib.sha256(old_path.read_bytes()).hexdigest()
    defaults = service.projects.get_project(source.project_id).defaults.model_copy(deep=True)

    derived = next_video(service, source)

    assert derived.revision == 1 and derived.parent_revision is None
    assert derived.created_by is CreatedBy.next_video
    assert derived.derived_from.video_id == source.id
    assert derived.derived_from.revision == source.revision
    assert derived.stage is VideoStage.draft
    assert (derived.topic, derived.material, derived.reference, derived.script) == (
        "", [], None, None,
    )
    assert derived.scenes == {} and derived.scene_order == []
    assert derived.settings.visual.art_style == source.settings.visual.art_style
    assert derived.settings.visual.character == source.settings.visual.character
    assert derived.settings.audio.voice == source.settings.audio.voice
    assert derived.settings.format.humor == source.settings.format.humor
    assert derived.settings.origins["/format/humor"] is Origin.user
    assert derived.settings.locks == source.settings.locks
    assert derived.settings.language == source.settings.language
    assert derived.settings.target_duration_s == source.settings.target_duration_s
    assert not service.validate(derived)

    changed = service.commit(plan(service, derived, [set_op("/topic", "New synthetic topic")]), 1)
    assert changed.revision == 2
    assert hashlib.sha256(old_path.read_bytes()).hexdigest() == old_hash
    assert service.projects.get_project(source.project_id).defaults == defaults
    reopened_db = Database.open(layout.state_db)
    try:
        reopened = ProjectService(SqliteProjectStore(reopened_db, layout), service.catalog)
        assert reopened.view(source.id) == source
        assert reopened.view(derived.id).topic == "New synthetic topic"
        assert reopened.projects.get_video(derived.id, 1) == derived
    finally:
        reopened_db.close()


def test_8_varied_theme_avoids_both_recent_videos(service: ProjectService) -> None:
    first = project_video(service)
    second = next_video(service, first)
    third = next_video(service, second)
    fourth = next_video(service, third)
    themes = [video.settings.visual.theme_id for video in (first, second, third, fourth)]
    assert len(set(themes[:3])) == 3
    assert themes[3] == themes[0]
    for video in (second, third, fourth):
        assert video.settings.origins["/visual/theme_id"] is Origin.derived
        assert video.settings.visual.art_style == first.settings.visual.art_style
        assert not service.validate(video)


def test_8_same_seed_and_inputs_choose_the_same_catalog_values(service: ProjectService) -> None:
    first = project_video(service)
    project = service.projects.get_project(first.project_id)
    first.settings.locks.update({
        LockKey.register: LockState.varied, LockKey.story_structure: LockState.varied,
        LockKey.character: LockState.varied, LockKey.caption_mode: LockState.varied,
    })
    before = first.model_copy(deep=True)
    a = service.pick_varied(project, [first], seed=29)
    b = service.pick_varied(project, [first], seed=29)
    assert a == b
    assert first == before
    assert a.format.register_value != first.settings.format.register_value
    assert a.format.story_structure != first.settings.format.story_structure
    probe = first.model_copy(update={"settings": a, "scenes": {}, "scene_order": []})
    assert not service.validate(probe)


def test_8_two_candidates_avoid_the_newest_when_both_were_used(service: ProjectService) -> None:
    first = project_video(service)
    first.settings.locks = {LockKey.humor: LockState.varied}
    first.settings.format.humor = Humor.none
    second = first.model_copy(deep=True)
    second.settings.format.humor = Humor.light
    project = service.projects.get_project(first.project_id)
    picked = service.pick_varied(project, [first, second], seed=5)
    assert picked.format.humor.value == "none"


def test_8_single_candidate_and_locked_values_remain_exact(service: ProjectService) -> None:
    first = project_video(service)
    current_style = first.settings.visual.art_style.id

    class SingleStyleRegistry(Registry):
        def list(self, kind, *, video=None):
            items = super().list(kind, video=video)
            if kind != "art_style":
                return items
            return [item for item in items if item.id == current_style]

    first.settings.locks = {key: LockState.locked for key in LockKey}
    first.settings.locks[LockKey.art_style] = LockState.varied
    project = service.projects.get_project(first.project_id)
    picked = derive.pick_varied(SingleStyleRegistry(), project, [first], seed=4)
    assert picked == first.settings
    picked.extra_instructions.append("Synthetic instruction")
    assert first.settings.extra_instructions == []


def test_8_catalog_order_does_not_change_seeded_selection(service: ProjectService) -> None:
    class ReversedRegistry(Registry):
        def list(self, kind, *, video=None):
            return list(reversed(super().list(kind, video=video)))

    first = project_video(service)
    project = service.projects.get_project(first.project_id)
    picked = service.pick_varied(project, [first], seed=71)
    reversed_pick = derive.pick_varied(ReversedRegistry(), project, [first], seed=71)
    assert picked == reversed_pick


def test_8_varied_layout_and_caption_keep_typewriter_compatible(service: ProjectService) -> None:
    first = project_video(service)
    first.settings.locks = {
        LockKey.layout: LockState.varied, LockKey.caption_mode: LockState.varied,
        LockKey.character_role: LockState.varied, LockKey.character: LockState.varied,
    }
    project = service.projects.get_project(first.project_id)
    for seed in range(4):
        settings = service.pick_varied(project, [first], seed=seed)
        template = service.catalog.get("template", settings.format.layout.id)
        assert settings.caption.mode in template.caption_modes
        if settings.caption.mode.value == "typewriter":
            assert template.dialog_box
        assert not service.validate(first.model_copy(update={"settings": settings}))


def test_9a_deriving_older_source_uses_project_recent_heads(service: ProjectService) -> None:
    first = project_video(service)
    second = next_video(service, first)
    third = next_video(service, second)
    derived = next_video(service, first)
    assert derived.settings.visual.theme_id not in {
        second.settings.visual.theme_id, third.settings.visual.theme_id,
    }
    assert derived.derived_from.video_id == first.id


def test_9a_cross_project_source_is_rejected_without_new_video(service: ProjectService) -> None:
    first = project_video(service)
    other = project_video(service)
    project = service.projects.get_project(other.project_id)
    with pytest.raises(AppError) as error:
        service.create_video(
            project.id, CreateVideoRequest(from_video_id=first.id, preset_id=None)
        )
    assert error.value.code == "not_found"
    assert service.projects.get_project(project.id).video_ids == project.video_ids


def test_8_missing_locked_catalog_id_is_reported_without_a_snapshot(
    service: ProjectService,
) -> None:
    first = project_video(service)
    first.settings.visual.theme_id = "missing_theme"
    first.settings.locks = {key: LockState.locked for key in LockKey}
    project = service.projects.get_project(first.project_id)
    with pytest.raises(AppError) as error:
        service.pick_varied(project, [first], seed=2)
    assert error.value.code == "unknown_catalog_id"


def test_8_character_variation_changes_parts_not_only_preset_metadata(
    service: ProjectService,
) -> None:
    first = project_video(service)
    first.settings.locks = {LockKey.character: LockState.varied}
    project = service.projects.get_project(first.project_id).model_copy(
        update={"defaults": first.settings}
    )
    settings = service.pick_varied(project, [], seed=17)
    settings.visual.character.preset_id = "synthetic_character"
    source = first.model_copy(update={"settings": settings})
    picked = service.pick_varied(project, [source], seed=17)
    assert picked.visual.character.slots != source.settings.visual.character.slots


def test_8_varied_bgm_avoids_both_recent_tracks(service: ProjectService) -> None:
    first = project_video(service)
    second = next_video(service, first)
    third = next_video(service, second)
    fourth = next_video(service, third)
    recent = {second.settings.audio.bgm.entry.id, third.settings.audio.bgm.entry.id}
    assert len(recent) == 2
    entry = fourth.settings.audio.bgm.entry
    assert entry.id not in recent
    assert entry.id in {item.id for item in service.catalog.list("bgm")}
    manifest = service.catalog.get("bgm", entry.id, entry.revision)
    assert manifest.mood == fourth.settings.audio.bgm.mood


def test_9a_character_free_source_derives_next_video(service: ProjectService) -> None:
    first = project_video(service)
    change = plan(
        service, first,
        [set_op("/settings/format/character_role", "none"),
         set_op("/settings/visual/character", None)],
        reasons=[ConfirmationReason.lock_change], locked=[LockKey.character],
    )
    source = service.commit(change, first.revision)
    assert not service.validate(source)

    derived = next_video(service, source)

    assert derived.settings.format.character_role is CharacterRole.none
    assert derived.settings.visual.character is None
    assert derived.derived_from.video_id == source.id


def test_8_varied_role_may_choose_no_character(service: ProjectService) -> None:
    first = project_video(service)
    first.settings.locks = {
        LockKey.character_role: LockState.varied, LockKey.character: LockState.varied,
    }
    project = service.projects.get_project(first.project_id)
    roles = {
        service.pick_varied(project, [first], seed=seed).format.character_role
        for seed in range(12)
    }
    assert CharacterRole.none in roles


def test_8_impossible_varied_value_fails_after_bounded_search(service: ProjectService) -> None:
    class KoreanOnlyVoices(Registry):
        calls = 0

        def get(self, kind, item_id, revision=None):
            KoreanOnlyVoices.calls += 1
            manifest = super().get(kind, item_id, revision)
            if kind == "voice":
                manifest = manifest.model_copy(update={"languages": [Language.ko]})
            return manifest

    first = project_video(service)
    project = service.projects.get_project(first.project_id)
    settings = project.defaults.model_copy(update={
        "language": Language.en,
        "locks": {key: LockState.varied for key in LockKey},
    })
    with pytest.raises(AppError) as error:
        derive.pick_varied(KoreanOnlyVoices(), project, [], 1, settings=settings)
    assert error.value.code == "invalid_combination"
    assert KoreanOnlyVoices.calls < 50_000


def test_8_varied_bgm_skips_uploads_of_other_projects(
    service: ProjectService, tmp_path: Path
) -> None:
    first = project_video(service)
    others: set[str] = set()
    for _ in range(40):
        item_id = new_typeid("u")
        others.add(item_id)
        staged = tmp_path / "staging" / item_id
        staged.mkdir(parents=True)
        wav = tone_wav(staged / f"{item_id}.wav", duration_ms=1000).read_bytes()
        raw = load_json("contracts/valid/bgm_upload.json")
        raw.update(
            id=item_id, upload_id=item_id, file=f"{item_id}.wav", channels=1, duration_ms=1000,
            sha256=hashlib.sha256(wav).hexdigest(),
            project_id="p_0cvg4rwzzp8zp90cpp9shhp80x",
        )
        (staged / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
        service.catalog.register_generated("bgm", staged)
    source = first
    for _ in range(6):
        source = next_video(service, source)
        assert source.settings.audio.bgm.entry.id not in others
