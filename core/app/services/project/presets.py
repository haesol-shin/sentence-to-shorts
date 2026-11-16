"""Preset snapshots: save reusable settings and apply them as changes.

A preset stores only ``PresetSettings``. Language, target duration, topic,
material, reference, script, scenes, generated results and origin pointers are
not saved. Saving reads the current revision once, and ``from_video`` pins that
revision, so later edits of the video never change the preset.

Applying a preset keeps the video language and length, writes the stored values
with origin preset, and never changes the lock map. A preset is a lower origin
than user and reference values, so those values stay even though this path has no
confirmation channel.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from app.ports import AppError
from app.schemas.api import PresetRequest
from app.schemas.change import (
    ChangePlan,
    ChangeSource,
    ChangeStatus,
    Effects,
    SetOp,
    Target,
)
from app.schemas.common import Origin
from app.schemas.preset import Preset
from app.schemas.settings import PresetSettings, Settings
from app.schemas.video import CreatedBy, DerivedFrom, Video, VideoStage
from app.services.project import revision, state

if TYPE_CHECKING:
    from app.services.project.service import ProjectService

_PRESET_FIELDS = tuple(PresetSettings.model_fields)
"""The only settings fields a preset may store. Origins and language are absent."""

_MUTABLE_REGIONS = ("format", "visual", "audio", "caption", "motion")
"""Preset regions an existing video may adopt. Locks are not adopted silently."""

_CARRIED_ORIGINS = frozenset({"/language", "/target_duration_s"})
_EXTRA_PATH = "/settings/extra_instructions"
_DRAFT_VIDEO = "v_0" + "0" * 25
_DRAFT_PROJECT = "p_0" + "0" * 25


def save_preset(service: ProjectService, project_id: str, req: PresetRequest) -> Preset:
    """Store a preset made from the current revision of one of the project's videos."""
    project = service.projects.get_project(project_id)
    video = service.projects.get_video(req.video_id)
    if video.project_id != project.id or video.owner_id != project.owner_id:
        raise AppError("not_found")
    settings = PresetSettings.model_validate(
        video.settings.model_dump(mode="json", by_alias=True, include=set(_PRESET_FIELDS))
    )
    preset = Preset(
        schema_version=1,
        id=service.projects.new_id("ps"),
        owner_id=project.owner_id,
        project_id=project.id,
        name=req.name,
        created_at=revision.now(),
        from_video=DerivedFrom(video_id=video.id, revision=video.revision),
        settings=settings,
    )
    service.projects.put_preset(preset)
    return preset


def get_preset(service: ProjectService, project_id: str, preset_id: str) -> Preset:
    """A preset of this project. The store port only lists, so the lookup is local."""
    for preset in service.projects.list_presets(project_id):
        if preset.id == preset_id:
            return preset
    raise AppError("not_found")


def _pinned(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"id", "revision"}


def _leaves(path: str, value: Any) -> Iterator[tuple[str, Any]]:
    """Split a dumped settings value into paths whose parent already exists.

    A pinned reference stays one value so its id and revision move together.
    Other objects recurse; a nullable entry such as the BGM reference is still
    a leaf because its parent object always exists.
    """
    if _pinned(value):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(f"{path}/{key}", child)
    else:
        yield path, value


def _region_leaves(name: str, value: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    if name == "visual":
        # The character can move between null and an object, so it is one value.
        yield "/settings/visual/art_style", value["art_style"]
        yield "/settings/visual/theme_id", value["theme_id"]
        yield "/settings/visual/character", value["character"]
        return
    if name == "audio":
        # gain_db_x10 has digits, so the whole BGM object is its addressable unit.
        yield "/settings/audio/voice", value["voice"]
        yield "/settings/audio/bgm", value["bgm"]
        yield "/settings/audio/sfx_enabled", value["sfx_enabled"]
        return
    yield from _leaves(f"/settings/{name}", value)


def _ops(preset: Preset) -> list[SetOp]:
    """One allowlisted leaf op per stored value, plus extra instructions.

    The guards compare every op against the state before it, so a higher origin
    or a locked value at a leaf stays. The lock map, language, target duration
    and origins have no op here, so none of them can move through this path.
    """
    ops = [
        SetOp(op="set", path=path, value=value, origin=Origin.preset)
        for name in _MUTABLE_REGIONS
        for path, value in _region_leaves(
            name, getattr(preset.settings, name).model_dump(mode="json", by_alias=True)
        )
    ]
    ops.append(
        SetOp(
            op="set",
            path=_EXTRA_PATH,
            value=list(preset.settings.extra_instructions),
            origin=Origin.preset,
        )
    )
    return ops


def _draft(settings: Settings) -> Video:
    """Throwaway draft used to reuse the pure op guards in ``state``."""
    return Video(
        schema_version=2,
        id=_DRAFT_VIDEO,
        project_id=_DRAFT_PROJECT,
        owner_id="owner",
        revision=1,
        parent_revision=None,
        created_at=revision.now(),
        created_by=CreatedBy.create,
        change_id=None,
        stage=VideoStage.draft,
        derived_from=None,
        topic="",
        material=[],
        reference=None,
        settings=settings,
        script=None,
        scene_order=[],
        scenes={},
    )


def settings_for(base: Settings, preset: Preset, *, preserve_existing: bool = False) -> Settings:
    """Settings for a new video initialized from a preset.

    ``preserve_existing`` is for the combined case where ``base`` already came
    from a source video: preset values pass through the origin and lock guards,
    so existing locks and higher user/reference values stay. Locks come from
    ``base`` then, not from the preset. The fresh case replaces every preset
    field including the lock map.
    """
    if preserve_existing:
        return state.apply(_draft(base), _ops(preset), Origin.user).video.settings
    origins: dict[str, Origin] = {
        pointer: origin
        for pointer, origin in base.origins.items()
        if pointer in _CARRIED_ORIGINS
    }
    for op in _ops(preset):
        if op.path != _EXTRA_PATH:
            origins[op.path.removeprefix("/settings")] = Origin.preset
    return Settings(
        language=base.language,
        target_duration_s=base.target_duration_s,
        format=preset.settings.format.model_copy(deep=True),
        visual=preset.settings.visual.model_copy(deep=True),
        audio=preset.settings.audio.model_copy(deep=True),
        caption=preset.settings.caption.model_copy(deep=True),
        motion=preset.settings.motion.model_copy(deep=True),
        locks=dict(preset.settings.locks),
        origins=origins,
        extra_instructions=list(preset.settings.extra_instructions),
    )


def apply_preset(
    service: ProjectService, video_id: str, preset_id: str, base_revision: int
) -> Video:
    """Apply a preset to an existing video as one persisted, unconfirmed change.

    The plan names no locks, no language, no length and no confirmation reason.
    Values owned by user or reference origins, and values protected by existing
    locks, are therefore left in place by the normal change guards. Extra
    instructions have no allowed origin pointer, so the preset list replaces
    them.
    """
    head = service.projects.get_video(video_id)
    revision.require_head(head, base_revision)
    preset = get_preset(service, head.project_id, preset_id)
    if preset.owner_id != head.owner_id:
        raise AppError("not_found")
    ops = _ops(preset)
    # Pure preview: report the values the guards keep, without confirming them.
    kept = state.apply(head, ops, state.SOURCE_ORIGIN[ChangeSource.direct])
    plan = ChangePlan(
        schema_version=2,
        id=service.projects.new_id("c"),
        video_id=head.id,
        base_revision=head.revision,
        created_at=revision.now(),
        source=ChangeSource.direct,
        target=Target(scene_id=None, pointer=None),
        ops=ops,
        effects=Effects(
            script=False,
            scene_ids_text=[],
            scene_ids_tts=[],
            scene_ids_render=[],
            mix=False,
            assemble=False,
            locked_keys=list(kept.locked_keys),
            overwrites_user_values=list(kept.overwrites_user_values),
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
    return service.commit(plan, base_revision)


__all__ = ["apply_preset", "get_preset", "save_preset", "settings_for"]
