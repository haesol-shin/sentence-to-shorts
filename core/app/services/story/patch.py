"""Typed patches: the only place model output becomes change plan ops.

Every story route returns a Pydantic model, then this module rechecks that the
proposed values respect locks, origins and the request target. The checks run
once for every route, so a new route cannot skip them by building ops itself.

Prompt files live next to the routes they serve: ``prompts/<route>/prompt.md``.
The loader strips the front matter, checks that the data variables match the
declaration and returns only the trusted body as the system prompt. User text
and material travel as data parts, never inside the system prompt.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.ports import (
    AppError,
    CatalogPort,
    JobContext,
    LlmPart,
    LlmPort,
    LlmRequest,
    LlmResult,
    LlmTask,
    UnknownCatalogId,
)
from app.schemas.change import SetOp, Target
from app.schemas.common import (
    CaptionMode,
    CatalogId,
    CharacterRole,
    ContractModel,
    Language,
    Mood,
    Origin,
    PinnedRef,
)
from app.schemas.job import Stage, WaitingOn
from app.schemas.settings import (
    CaptionPosition,
    CharacterMotion,
    Humor,
    LockKey,
    LockState,
    ProgressMode,
    Register,
    Transition,
)
from app.schemas.video import Video

PROMPT_ROOT = Path(__file__).resolve().parent / "prompts"

SET_PATH_PATTERN = (
    r"^/(topic|settings(/[a-z_]+)+|scenes/[a-z]{1,2}_[0-7][0-9a-hjkmnp-tv-z]{25}"
    r"/(beat_label|lines|visual)(/[A-Za-z0-9_]+)*)$"
)

ORIGIN_RANK: dict[Origin, int] = {
    Origin.user: 5,
    Origin.reference: 4,
    Origin.preset: 3,
    Origin.card: 2,
    Origin.llm: 1,
    Origin.default: 0,
    Origin.derived: 0,
}


class SkipReason(StrEnum):
    """Why a proposed value did not become an op."""

    locked = "locked"
    lower_origin = "lower_origin"
    outside_target = "outside_target"


class ValuePatch(ContractModel):
    """One value the model proposed, with the origin the service assigned it."""

    path: Annotated[str, Field(pattern=SET_PATH_PATTERN)]
    value: Any
    origin: Origin = Origin.llm


@dataclass(frozen=True)
class PatchOutcome:
    ops: list[SetOp]
    skipped: list[tuple[str, SkipReason]]


class SettingsValues(ContractModel):
    """Settings a story route may propose. Public names match the prompt data.

    ``register`` is aliased because the model base class already owns that name.
    """

    language: Language | None = None
    target_duration_s: Literal[30, 60, 120] | None = None
    story_structure: CatalogId | None = None
    layout: CatalogId | None = None
    character_role: CharacterRole | None = None
    register_value: Annotated[Register | None, Field(alias="register")] = None
    humor: Humor | None = None
    progress_mode: ProgressMode | None = None
    scene_count: Annotated[int, Field(ge=3, le=20)] | None = None
    art_style: CatalogId | None = None
    theme_id: CatalogId | None = None
    voice: CatalogId | None = None
    bgm_mood: Mood | None = None
    bgm_enabled: bool | None = None
    sfx_enabled: bool | None = None
    caption_mode: CaptionMode | None = None
    caption_position: CaptionPosition | None = None
    caption_highlight: bool | None = None
    transition: Transition | None = None
    character_motion: CharacterMotion | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


@dataclass(frozen=True)
class FieldSpec:
    pointer: str
    catalog_kind: str | None = None
    check_kind: str | None = None


FIELDS: dict[str, FieldSpec] = {
    "language": FieldSpec("/settings/language"),
    "target_duration_s": FieldSpec("/settings/target_duration_s"),
    "story_structure": FieldSpec(
        "/settings/format/story_structure", check_kind="story_structure"
    ),
    "layout": FieldSpec("/settings/format/layout", "template"),
    "character_role": FieldSpec("/settings/format/character_role"),
    "register_value": FieldSpec("/settings/format/register"),
    "humor": FieldSpec("/settings/format/humor"),
    "progress_mode": FieldSpec("/settings/format/progress_mode"),
    "scene_count": FieldSpec("/settings/format/scene_count"),
    "art_style": FieldSpec("/settings/visual/art_style", "art_style"),
    "theme_id": FieldSpec("/settings/visual/theme_id"),
    "voice": FieldSpec("/settings/audio/voice", "voice"),
    "bgm_mood": FieldSpec("/settings/audio/bgm/mood"),
    "bgm_enabled": FieldSpec("/settings/audio/bgm/enabled"),
    "sfx_enabled": FieldSpec("/settings/audio/sfx_enabled"),
    "caption_mode": FieldSpec("/settings/caption/mode"),
    "caption_position": FieldSpec("/settings/caption/position"),
    "caption_highlight": FieldSpec("/settings/caption/highlight"),
    "transition": FieldSpec("/settings/motion/transition"),
    "character_motion": FieldSpec("/settings/motion/character_motion"),
}

LOCK_POINTERS: tuple[tuple[str, LockKey], ...] = tuple(
    sorted(
        (
            ("/settings/format/story_structure", LockKey.story_structure),
            ("/settings/format/layout", LockKey.layout),
            ("/settings/format/character_role", LockKey.character_role),
            ("/settings/format/register", LockKey.register),
            ("/settings/format/humor", LockKey.humor),
            ("/settings/visual/art_style", LockKey.art_style),
            ("/settings/visual/theme_id", LockKey.theme),
            ("/settings/audio/voice", LockKey.voice),
            ("/settings/audio/bgm", LockKey.bgm),
            ("/settings/caption/mode", LockKey.caption_mode),
            ("/settings/caption/font_id", LockKey.caption_font),
            ("/settings/motion/transition", LockKey.transition),
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

SETTINGS_PREFIX = "/settings"


def lock_key_for(path: str) -> LockKey | None:
    for prefix, key in LOCK_POINTERS:
        if path == prefix or path.startswith(prefix + "/"):
            return key
    return None


def current_origin(video: Video, path: str) -> Origin:
    if not path.startswith(SETTINGS_PREFIX + "/"):
        return Origin.default
    origin = video.settings.origins.get(path[len(SETTINGS_PREFIX) :])
    return origin if origin is not None else Origin.default


def within_target(path: str, target: Target | None) -> bool:
    if target is None:
        return True
    if target.pointer is not None:
        pointer = target.pointer
        if path != pointer and not path.startswith(pointer + "/"):
            return False
    if target.scene_id is not None:
        prefix = f"/scenes/{target.scene_id}/"
        if not path.startswith(prefix):
            return False
    return True


def rejection(video: Video, patch: ValuePatch, target: Target | None) -> SkipReason | None:
    if not within_target(patch.path, target):
        return SkipReason.outside_target
    key = lock_key_for(patch.path)
    if key is not None and video.settings.locks.get(key) is LockState.locked:
        return SkipReason.locked
    if ORIGIN_RANK[patch.origin] < ORIGIN_RANK[current_origin(video, patch.path)]:
        return SkipReason.lower_origin
    return None


def _last_wins(patches: list[ValuePatch]) -> list[ValuePatch]:
    """One patch per path: the highest origin wins, ties keep the later value."""
    winners: dict[str, ValuePatch] = {}
    order: list[str] = []
    for patch in patches:
        current = winners.get(patch.path)
        if current is None:
            order.append(patch.path)
            winners[patch.path] = patch
        elif ORIGIN_RANK[patch.origin] >= ORIGIN_RANK[current.origin]:
            winners[patch.path] = patch
    return [winners[path] for path in order]


def build_ops(
    video: Video, patches: list[ValuePatch], *, target: Target | None = None
) -> PatchOutcome:
    """Validate proposed values and turn the accepted ones into set ops."""
    ops: list[SetOp] = []
    skipped: list[tuple[str, SkipReason]] = []
    for patch in _last_wins(patches):
        reason = rejection(video, patch, target)
        if reason is not None:
            skipped.append((patch.path, reason))
            continue
        ops.append(SetOp(op="set", path=patch.path, value=patch.value, origin=patch.origin))
    return PatchOutcome(ops=ops, skipped=skipped)


def check_catalog_ids(values: SettingsValues, catalog: CatalogPort) -> None:
    """Raise ValueError when a value names an id the registry does not have.

    ``catalog_kind`` marks values that are stored as a pinned reference.
    ``check_kind`` validates a plain catalog id that stays a string.
    """
    for name, spec in FIELDS.items():
        raw = getattr(values, name)
        kind = spec.check_kind or spec.catalog_kind
        if raw is None or kind is None:
            continue
        try:
            catalog.get(kind, raw)
        except UnknownCatalogId as error:
            raise ValueError(f"{name} is not a registered {kind}: {raw}") from error


def check_theme_id(
    values: SettingsValues, catalog: CatalogPort, current_art_style: str
) -> None:
    """A theme id belongs to an art style, so it is checked inside that style."""
    if values.theme_id is None:
        return
    style_id = values.art_style or current_art_style
    try:
        manifest = catalog.get("art_style", style_id)
    except UnknownCatalogId as error:
        raise ValueError(f"unknown art style: {style_id}") from error
    themes = getattr(manifest, "themes", [])
    if values.theme_id not in {theme.id for theme in themes}:
        raise ValueError(f"{values.theme_id} is not a theme of {style_id}")


def _quoted(evidence: Mapping[str, str], name: str, message: str) -> bool:
    quote = evidence.get(name)
    return bool(quote) and quote in message


def field_patches(
    values: SettingsValues,
    *,
    catalog: CatalogPort,
    origin: Origin,
    evidence: Mapping[str, str] | None = None,
    message: str = "",
) -> list[ValuePatch]:
    """Turn typed settings values into patches, pinning catalog references."""
    patches: list[ValuePatch] = []
    quotes = evidence or {}
    for name, spec in FIELDS.items():
        raw = getattr(values, name)
        if raw is None:
            continue
        if spec.catalog_kind is not None:
            pinned: PinnedRef = catalog.pin(spec.catalog_kind, raw)
            value: Any = pinned.model_dump(mode="json")
        elif isinstance(raw, StrEnum):
            value = raw.value
        else:
            value = raw
        alias = type(values).model_fields[name].alias
        public_name = alias or name
        patch_origin = (
            Origin.user if _quoted(quotes, public_name, message) else origin
        )
        patches.append(ValuePatch(path=spec.pointer, value=value, origin=patch_origin))
    return patches


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("prompt is missing front matter")
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        raise ValueError("prompt front matter is not closed")
    matter = yaml.safe_load("\n".join(lines[1:end]))
    if matter is None:
        matter = {}
    if not isinstance(matter, dict):
        raise ValueError("prompt front matter is not a mapping")
    return matter, "\n".join(lines[end + 1 :]).strip()


def load_prompt(route: str, data: Mapping[str, Any]) -> str:
    """Return the trusted system body for a resolved route.

    The front matter must name the same route and declare exactly the data
    variables the caller passes. A mismatch means the request would send an
    undeclared or missing value, so it is rejected before the model runs.
    """
    path = PROMPT_ROOT / route / "prompt.md"
    if not path.is_file():
        raise AppError("internal", detail={"prompt": route, "problem": "missing"})
    try:
        matter, body = _split_front_matter(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise AppError("internal", detail={"prompt": route, "problem": "front_matter"}) from error
    declared = matter.get("data_variables")
    version = matter.get("version")
    if matter.get("route") != route:
        raise AppError("internal", detail={"prompt": route, "problem": "route"})
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise AppError("internal", detail={"prompt": route, "problem": "version"})
    if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
        raise AppError("internal", detail={"prompt": route, "problem": "variables"})
    if set(declared) != set(data):
        raise AppError("internal", detail={"prompt": route, "problem": "variables"})
    if not body:
        raise AppError("internal", detail={"prompt": route, "problem": "body"})
    return body + "\n"


def _data_text(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)


def _repair_text(error: ValueError) -> str:
    return json.dumps({"validation_error": str(error)[:1000]}, ensure_ascii=False)


REPAIR_NOTE = "\n\n# Repair\n\nReturn corrected JSON that validates against the schema.\n"


ModelT = TypeVar("ModelT", bound=BaseModel)
StepT = TypeVar("StepT")


def llm_step(
    ctx: JobContext, stage: Stage, *, done: int, total: int, call: Callable[[], StepT]
) -> StepT:
    """Run one LLM call as a recorded stage: waiting on the model, then one step done."""
    with ctx.stage(stage):
        ctx.progress(done=done, total=total, waiting_on=WaitingOn.llm)
        value = call()
        ctx.progress(done=done + 1, total=total)
    return value


def _validated(
    result: LlmResult, model: type[ModelT], check: Callable[[ModelT], None] | None
) -> ModelT:
    if result.parsed is None:
        raise ValueError("output is not a JSON object")
    value = model.model_validate(result.parsed)
    if check is not None:
        check(value)
    return value


def complete_json(
    llm: LlmPort,
    *,
    task: LlmTask,
    route: str,
    model: type[ModelT],
    data: Mapping[str, Any],
    max_output_tokens: int,
    ctx: JobContext,
    check: Callable[[ModelT], None] | None = None,
) -> ModelT:
    """Call the model once, repair an invalid output once, then fail.

    A second invalid output is a job error, never a silent empty result. The
    repair call appends one trusted repair note to the system prompt and sends
    the validation error as a data part, so user text stays out of system.
    """
    system = load_prompt(route, data)
    parts = [LlmPart(kind="text", text=_data_text(data))]
    request = LlmRequest(
        task=task,
        route=route,
        system=system,
        parts=parts,
        output_schema=model.model_json_schema(),
        max_output_tokens=max_output_tokens,
    )
    first = llm.complete(
        request,
        owner_id=ctx.owner_id,
        cancel=ctx.cancel,
        deadline=ctx.deadline,
        on_request=ctx.record_request,
    )
    ctx.record_usage(first.usage)
    try:
        return _validated(first, model, check)
    except ValueError as error:
        second_request = LlmRequest(
            task=task,
            route=route,
            system=system + REPAIR_NOTE,
            parts=[*parts, LlmPart(kind="text", text=_repair_text(error))],
            output_schema=model.model_json_schema(),
            max_output_tokens=max_output_tokens,
        )
        second = llm.complete(
            second_request,
            owner_id=ctx.owner_id,
            cancel=ctx.cancel,
            deadline=ctx.deadline,
            on_request=ctx.record_request,
        )
        ctx.record_usage(second.usage)
        try:
            return _validated(second, model, check)
        except ValueError as final:
            raise AppError(
                "llm_invalid_output", detail={"task": task.value, "route": route}
            ) from final


__all__ = [
    "FIELDS",
    "PROMPT_ROOT",
    "PatchOutcome",
    "SettingsValues",
    "SkipReason",
    "ValuePatch",
    "build_ops",
    "check_catalog_ids",
    "check_theme_id",
    "complete_json",
    "current_origin",
    "field_patches",
    "llm_step",
    "load_prompt",
    "lock_key_for",
    "rejection",
    "within_target",
]
