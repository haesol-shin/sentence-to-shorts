"""Preset saving, lookup, new-video initialization and application."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.plugins.registry import Registry
from app.ports import AppError
from app.schemas.api import CreateProjectRequest, CreateVideoRequest, PresetRequest
from app.schemas.change import (
    ChangePlan,
    ChangeSource,
    ChangeStatus,
    Effects,
    SetOp,
    Target,
)
from app.schemas.common import Language, Origin
from app.schemas.preset import Preset
from app.schemas.project import Project
from app.schemas.settings import (
    CaptionMode,
    Humor,
    LockKey,
    LockState,
    PresetSettings,
    Register,
)
from app.schemas.video import CreatedBy, Video
from app.services.project import presets, state
from app.services.project.service import ProjectService
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore
from app.storage.sqlite import Database
from tests.conftest import load_json


def locks_value(locks: dict[LockKey, LockState]) -> dict[str, str]:
    return {key.value: value.value for key, value in locks.items()}


DEFAULT_LOCKS = locks_value(state.DEFAULT_LOCKS)


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


def make_project_video(service: ProjectService) -> tuple[Project, Video]:
    project = service.create_project(CreateProjectRequest(title=None, language=Language.ko))
    video = service.create_video(
        project.id, CreateVideoRequest(from_video_id=None, preset_id=None)
    )
    return project, video


def add_video(service: ProjectService, project: Project) -> Video:
    return service.create_video(
        project.id, CreateVideoRequest(from_video_id=None, preset_id=None)
    )


def set_op(path: str, value: Any, origin: Origin = Origin.user) -> SetOp:
    return SetOp(op="set", path=path, value=value, origin=origin)


def commit_ops(
    service: ProjectService,
    video: Video,
    ops: list[SetOp],
    *,
    source: ChangeSource = ChangeSource.direct,
) -> Video:
    plan = ChangePlan(
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
    service.projects.put_change(plan)
    return service.commit(plan, video.revision)


def save(service: ProjectService, project: Project, video: Video) -> Preset:
    return presets.save_preset(
        service, project.id, PresetRequest(video_id=video.id, name="합성 프리셋")
    )


def test_13_preset_stores_only_settings_and_pins_the_saved_revision(
    service: ProjectService,
) -> None:
    project, video = make_project_video(service)
    full = Video.model_validate(load_json("contracts/valid/video_ko_just_three.json"))
    stored = service.projects.append_revision(
        video.model_copy(
            update={
                "revision": 2,
                "parent_revision": 1,
                "created_at": datetime.now(UTC),
                "created_by": CreatedBy.system,
                "topic": "합성 주제",
                "material": full.material,
                "reference": full.reference,
                "script": full.script,
                "scene_order": full.scene_order,
                "scenes": full.scenes,
            }
        )
    )

    preset = save(service, project, stored)

    assert preset.from_video is not None
    assert (preset.from_video.video_id, preset.from_video.revision) == (stored.id, 2)
    assert (preset.settings.format, preset.settings.locks) == (
        stored.settings.format,
        stored.settings.locks,
    )
    doc = preset.model_dump(mode="json")
    assert set(doc["settings"]) == set(PresetSettings.model_fields)
    for absent in (
        "topic",
        "material",
        "reference",
        "script",
        "scene_order",
        "scenes",
        "language",
        "target_duration_s",
        "origins",
    ):
        assert absent not in doc
        assert absent not in doc["settings"]

    service.projects.append_revision(
        stored.model_copy(
            update={
                "revision": 3,
                "parent_revision": 2,
                "created_at": datetime.now(UTC),
                "created_by": CreatedBy.system,
                "settings": stored.settings.model_copy(
                    update={"extra_instructions": ["합성 지시"]}
                ),
            }
        )
    )
    again = presets.get_preset(service, project.id, preset.id)
    assert again == preset
    assert again.from_video is not None and again.from_video.revision == 2
    assert again.settings.extra_instructions == []


def test_13_settings_for_a_fresh_preset_keeps_language_length_and_uses_preset_origins(
    service: ProjectService,
) -> None:
    project, video = make_project_video(service)
    source = commit_ops(
        service,
        video,
        [
            set_op("/settings/format/register", Register.casual.value),
            set_op(
                "/settings/locks",
                locks_value({**state.DEFAULT_LOCKS, LockKey.humor: LockState.locked}),
            ),
        ],
    )
    preset = save(service, project, source)
    base = project.defaults.model_copy(
        deep=True, update={"language": Language.en, "target_duration_s": 30}
    )
    base = base.model_copy(
        update={"origins": {**base.origins, "/format/humor": Origin.user}}
    )

    settings = presets.settings_for(base, preset)

    assert (settings.language, settings.target_duration_s) == (Language.en, 30)
    assert settings.format.register_value is Register.casual
    assert settings.locks[LockKey.humor] is LockState.locked
    assert settings.extra_instructions == preset.settings.extra_instructions
    assert {
        pointer
        for pointer, origin in settings.origins.items()
        if origin is not Origin.preset
    } == {"/language", "/target_duration_s"}
    assert settings.origins["/language"] is Origin.user
    assert settings.origins["/target_duration_s"] is Origin.default
    assert settings.origins["/format/register"] is Origin.preset
    assert settings.origins["/format/humor"] is Origin.preset
    assert settings.origins["/visual/character"] is Origin.preset
    assert settings.origins["/audio/bgm"] is Origin.preset
    assert "/format" not in settings.origins


def test_13_settings_for_a_preserved_preset_keeps_higher_values_and_locks(
    service: ProjectService,
) -> None:
    project, source = make_project_video(service)
    source = commit_ops(
        service,
        source,
        [
            set_op("/settings/format/register", Register.casual.value),
            set_op("/settings/format/humor", Humor.light.value),
            set_op("/settings/visual/theme_id", "arcade"),
            set_op(
                "/settings/locks",
                locks_value({**state.DEFAULT_LOCKS, LockKey.humor: LockState.locked}),
            ),
        ],
    )
    preset = save(service, project, source)
    target = add_video(service, project)
    target = commit_ops(
        service,
        target,
        [
            set_op("/settings/format/register", Register.neutral.value),
            set_op(
                "/settings/locks",
                locks_value({**state.DEFAULT_LOCKS, LockKey.theme: LockState.locked}),
            ),
        ],
    )
    target = commit_ops(
        service,
        target,
        [set_op("/settings/caption/mode", CaptionMode.phrase.value, Origin.reference)],
        source=ChangeSource.reference,
    )

    settings = presets.settings_for(target.settings, preset, preserve_existing=True)

    assert settings.format.register_value is Register.neutral
    assert settings.format.humor is Humor.light
    assert settings.caption.mode is CaptionMode.phrase
    assert settings.visual.theme_id == target.settings.visual.theme_id
    assert settings.locks[LockKey.theme] is LockState.locked
    assert settings.locks == target.settings.locks
    assert settings.origins["/format/humor"] is Origin.preset
    assert settings.origins["/format/story_structure"] is Origin.preset
    assert settings.origins["/format/register"] is Origin.user
    assert settings.origins["/caption/mode"] is Origin.reference
    assert settings.origins["/caption/position"] is Origin.preset
    assert settings.origins["/language"] == target.settings.origins["/language"]
    assert (
        settings.origins["/target_duration_s"]
        == target.settings.origins["/target_duration_s"]
    )


def test_13_apply_preset_writes_a_preset_origin_revision(service: ProjectService) -> None:
    project, source = make_project_video(service)
    source = commit_ops(
        service, source, [set_op("/settings/format/register", Register.casual.value)]
    )
    preset = save(service, project, source)
    target = add_video(service, project)

    applied = presets.apply_preset(service, target.id, preset.id, target.revision)

    assert (applied.revision, applied.parent_revision) == (2, 1)
    assert applied.created_by is CreatedBy.change
    assert applied.settings.format.register_value is Register.casual
    assert applied.settings.origins["/format/register"] is Origin.preset
    assert applied.settings.origins["/format/story_structure"] is Origin.preset
    assert applied.settings.language == target.settings.language
    assert applied.settings.target_duration_s == target.settings.target_duration_s
    assert (
        applied.settings.origins["/language"]
        == target.settings.origins["/language"]
    )
    assert (
        applied.settings.origins["/target_duration_s"]
        == target.settings.origins["/target_duration_s"]
    )
    assert applied.change_id is not None
    plan = service.projects.get_change(applied.change_id)
    assert (plan.status, plan.applied_revision) == (ChangeStatus.applied, 2)
    assert len(service.projects.list_revisions(target.id)) == 2


def test_13_apply_preset_keeps_higher_origins_and_locks(service: ProjectService) -> None:
    project, source = make_project_video(service)
    source = commit_ops(
        service,
        source,
        [
            set_op("/settings/format/register", Register.casual.value),
            set_op("/settings/format/humor", Humor.light.value),
            set_op("/settings/visual/theme_id", "arcade"),
            set_op(
                "/settings/locks",
                locks_value({**state.DEFAULT_LOCKS, LockKey.humor: LockState.locked}),
            ),
        ],
    )
    preset = save(service, project, source)
    target = add_video(service, project)
    target = commit_ops(
        service,
        target,
        [
            set_op("/settings/format/register", Register.neutral.value),
            set_op(
                "/settings/locks",
                locks_value({**state.DEFAULT_LOCKS, LockKey.theme: LockState.locked}),
            ),
        ],
    )
    target = commit_ops(
        service,
        target,
        [set_op("/settings/caption/mode", CaptionMode.phrase.value, Origin.reference)],
        source=ChangeSource.reference,
    )

    applied = presets.apply_preset(service, target.id, preset.id, target.revision)

    assert applied.revision == 4
    assert applied.settings.format.register_value is Register.neutral
    assert applied.settings.format.humor is Humor.light
    assert applied.settings.caption.mode is CaptionMode.phrase
    assert applied.settings.visual.theme_id == target.settings.visual.theme_id
    assert applied.settings.locks[LockKey.theme] is LockState.locked
    assert applied.settings.locks == target.settings.locks
    assert applied.settings.origins["/format/register"] is Origin.user
    assert applied.settings.origins["/caption/mode"] is Origin.reference
    assert applied.settings.origins["/format/humor"] is Origin.preset
    assert applied.settings.origins["/format/story_structure"] is Origin.preset
    plan = service.projects.get_change(applied.change_id)
    assert "/settings/format/register" in plan.effects.overwrites_user_values
    assert plan.confirmation_reasons == []


def test_13_apply_preset_rejects_a_stale_base(service: ProjectService) -> None:
    project, video = make_project_video(service)
    preset = save(service, project, video)

    with pytest.raises(AppError) as error:
        presets.apply_preset(service, video.id, preset.id, video.revision + 1)
    assert error.value.code == "revision_conflict"
    assert error.value.detail["current_revision"] == video.revision

    applied = presets.apply_preset(service, video.id, preset.id, video.revision)
    with pytest.raises(AppError) as error:
        presets.apply_preset(service, video.id, preset.id, video.revision)
    assert error.value.code == "revision_conflict"
    assert error.value.detail["current_revision"] == applied.revision


def test_13_presets_reject_cross_project_videos(service: ProjectService) -> None:
    project, video = make_project_video(service)
    preset = save(service, project, video)
    other_project, other_video = make_project_video(service)

    with pytest.raises(AppError) as error:
        presets.save_preset(
            service,
            other_project.id,
            PresetRequest(video_id=video.id, name="합성 프리셋"),
        )
    assert error.value.code == "not_found"
    with pytest.raises(AppError) as error:
        presets.get_preset(service, other_project.id, preset.id)
    assert error.value.code == "not_found"
    with pytest.raises(AppError) as error:
        presets.apply_preset(service, other_video.id, preset.id, other_video.revision)
    assert error.value.code == "not_found"
    assert presets.get_preset(service, project.id, preset.id) == preset


def test_13_preset_survives_a_service_restart(
    layout: Layout, catalog: Registry
) -> None:
    database = Database.open(layout.state_db)
    try:
        first = ProjectService(SqliteProjectStore(database, layout), catalog)
        project = first.create_project(
            CreateProjectRequest(title=None, language=Language.ko)
        )
        video = first.create_video(
            project.id, CreateVideoRequest(from_video_id=None, preset_id=None)
        )
        video = commit_ops(
            first, video, [set_op("/settings/format/register", Register.casual.value)]
        )
        preset = save(first, project, video)
    finally:
        database.close()

    reopened_db = Database.open(layout.state_db)
    try:
        reopened = ProjectService(SqliteProjectStore(reopened_db, layout), catalog)
        loaded = presets.get_preset(reopened, project.id, preset.id)
        assert loaded == preset
        assert loaded.from_video == preset.from_video
        assert reopened.projects.list_presets(project.id) == [preset]
        applied = presets.apply_preset(reopened, video.id, preset.id, video.revision)
        assert applied.revision == 3
        assert applied.settings.format.register_value is Register.casual
        assert applied.settings.origins["/format/humor"] is Origin.preset
        assert applied.settings.origins["/format/register"] is Origin.user
    finally:
        reopened_db.close()


def test_13_initial_preset_creates_revision_one(service: ProjectService) -> None:
    project, source = make_project_video(service)
    source = commit_ops(
        service,
        source,
        [
            set_op("/settings/format/register", Register.casual.value),
            set_op("/settings/format/humor", Humor.light.value),
            set_op(
                "/settings/locks",
                locks_value({**state.DEFAULT_LOCKS, LockKey.humor: LockState.locked}),
            ),
        ],
    )
    preset = save(service, project, source)

    created = service.create_video(
        project.id, CreateVideoRequest(from_video_id=None, preset_id=preset.id)
    )

    assert (created.revision, created.parent_revision) == (1, None)
    assert created.created_by is CreatedBy.create
    assert created.derived_from is None
    assert (created.topic, created.script) == ("", None)
    assert created.scene_order == [] and created.scenes == {}
    assert created.settings.format.register_value is Register.casual
    assert created.settings.format.humor is Humor.light
    assert created.settings.locks[LockKey.humor] is LockState.locked
    assert created.settings.language is project.defaults.language
    assert created.settings.target_duration_s == project.defaults.target_duration_s
    assert (
        created.settings.origins["/language"]
        is project.defaults.origins["/language"]
    )
    assert (
        created.settings.origins["/target_duration_s"]
        is project.defaults.origins["/target_duration_s"]
    )
    for name in (
        "/format/register",
        "/format/humor",
        "/visual/theme_id",
        "/visual/character",
        "/audio/bgm",
        "/audio/voice",
        "/caption/font_id",
        "/caption/mode",
        "/motion/transition",
    ):
        assert created.settings.origins[name] is Origin.preset
    for name in ("format", "visual", "audio", "caption", "motion"):
        assert f"/{name}" not in created.settings.origins
    updated = service.projects.get_project(project.id)
    assert updated.video_ids == [source.id, created.id]


def _full_video(service: ProjectService, project: Project) -> Video:
    """A project video with the valid Korean script and scenes attached."""
    video = add_video(service, project)
    full = Video.model_validate(load_json("contracts/valid/video_ko_just_three.json"))
    return service.projects.append_revision(
        video.model_copy(
            update={
                "revision": 2,
                "parent_revision": 1,
                "created_at": datetime.now(UTC),
                "created_by": CreatedBy.system,
                "script": full.script,
                "scene_order": full.scene_order,
                "scenes": full.scenes,
            }
        )
    )


def _add_extra_layer(
    service: ProjectService, video: Video, *, texts: bool = True
) -> Video:
    ops = [
        set_op(
            "/settings/caption/extra",
            [
                {
                    "language": "en",
                    "mode": "sentence",
                    "font_id": service.catalog.pin("font", "galmuri11").model_dump(),
                    "position": "top",
                }
            ],
        )
    ]
    if texts:
        for scene_id in video.scene_order:
            for index, _ in enumerate(video.scenes[scene_id].lines):
                ops.append(
                    set_op(
                        f"/scenes/{scene_id}/lines/{index}/extra_texts",
                        [{"language": "en", "text": "A short translation."}],
                    )
                )
    return commit_ops(service, video, ops)


def test_29_extra_layer_without_translations_can_be_committed(
    service: ProjectService,
) -> None:
    project, _ = make_project_video(service)
    video = _full_video(service, project)

    saved = _add_extra_layer(service, video, texts=False)

    assert saved.settings.caption.extra
    caption_codes = {
        issue.code for issue in service.validate(saved) if issue.code.startswith("caption")
    }
    assert caption_codes == {"caption_text_missing"}


def test_13_preset_does_not_store_the_extra_caption_layer(service: ProjectService) -> None:
    project, video = make_project_video(service)
    video = _add_extra_layer(service, video)

    preset = save(service, project, video)

    assert "extra" not in preset.model_dump(mode="json")["settings"]["caption"]
    assert preset.settings.caption.mode is CaptionMode.sentence


def test_13_applying_a_preset_keeps_the_extra_layer_and_texts(
    service: ProjectService,
) -> None:
    project, source = make_project_video(service)
    preset = save(service, project, source)
    target = _add_extra_layer(service, _full_video(service, project))
    before = target.model_dump(mode="json")

    applied = presets.apply_preset(service, target.id, preset.id, target.revision)

    assert applied.settings.caption.extra == target.settings.caption.extra
    for scene_id in applied.scene_order:
        assert [line.extra_texts for line in applied.scenes[scene_id].lines] == [
            line.extra_texts for line in target.scenes[scene_id].lines
        ]
    caption_codes = {
        issue.code for issue in service.validate(applied) if issue.code.startswith("caption")
    }
    assert caption_codes == set()
    assert applied.model_dump(mode="json")["scenes"] == before["scenes"]


def test_13_derived_preset_keeps_source_user_values_and_locks(service: ProjectService) -> None:
    project, source = make_project_video(service)
    source = commit_ops(service, source, [
        set_op("/settings/format/register", Register.neutral.value),
        set_op(
            "/settings/locks",
            locks_value({**source.settings.locks, LockKey.theme: LockState.locked}),
        ),
    ])
    template = add_video(service, project)
    template = commit_ops(service, template, [
        set_op("/settings/format/register", Register.casual.value),
        set_op("/settings/format/humor", Humor.light.value),
        set_op("/settings/visual/theme_id", "arcade"),
    ])
    preset = save(service, project, template)

    derived = service.create_video(
        project.id, CreateVideoRequest(from_video_id=source.id, preset_id=preset.id)
    )

    assert derived.settings.format.register_value is Register.neutral
    assert derived.settings.origins["/format/register"] is Origin.user
    assert derived.settings.format.humor is Humor.light
    assert derived.settings.origins["/format/humor"] is Origin.preset
    assert derived.settings.visual.theme_id == source.settings.visual.theme_id
    assert derived.settings.locks == source.settings.locks
    assert derived.derived_from.video_id == source.id
    assert derived.derived_from.revision == source.revision
    assert service.view(source.id) == source
