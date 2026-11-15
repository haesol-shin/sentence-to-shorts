"""Concept draft: one sentence fills every stage and the first script.

The draft route proposes values, the card supplies its own values, and this
module turns both into patches with explicit origins: user for a value the user
named and the service could quote, card for card values, llm for everything the
model inferred. Locked keys and higher-ranked origins are never overwritten.

A first script is written with the format values this draft accepts, because the
video does not hold them yet when the script route runs. An existing script is
left alone: rewriting it needs its own confirmation.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.ports import AppError, CatalogPort, JobContext, LlmPort, LlmTask, UnknownCatalogId
from app.schemas.change import Op
from app.schemas.common import CatalogId, ContractModel, Language, Origin
from app.schemas.format_card import FormatCard
from app.schemas.settings import Humor, Register
from app.schemas.video import Video
from app.services.story.patch import (
    SettingsValues,
    ValuePatch,
    build_ops,
    check_catalog_ids,
    check_theme_id,
    complete_json,
    field_patches,
)
from app.services.story.script import ScriptBrief, build_script_ops

DRAFT_ROUTE = "draft"
DRAFT_MAX_TOKENS = 1200
_SCENE_COUNT_FIELDS = {30: "short_30", 60: "minute_60", 120: "minutes_120"}


class DraftOutput(ContractModel):
    """Model output of the draft route. Card picks and settings values only."""

    card_id: CatalogId | None = None
    topic: Annotated[str, Field(min_length=1, max_length=500)]
    values: SettingsValues = Field(default_factory=SettingsValues)
    evidence: dict[str, Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=dict
    )


def _card(catalog: CatalogPort, card_id: str) -> FormatCard:
    try:
        manifest = catalog.get("format_card", card_id)
    except UnknownCatalogId as error:
        raise ValueError(f"unknown format card: {card_id}") from error
    if not isinstance(manifest, FormatCard):
        raise ValueError(f"not a format card: {card_id}")
    return manifest


def _check_template(catalog: CatalogPort, layout_id: str) -> None:
    try:
        catalog.get("template", layout_id)
    except UnknownCatalogId as error:
        raise ValueError(f"unknown layout: {layout_id}") from error


def _check_draft(
    out: DraftOutput,
    *,
    requested_card: str | None,
    catalog: CatalogPort,
    current_art_style: str,
) -> None:
    chosen = requested_card or out.card_id
    if chosen is None:
        raise ValueError("card_id is required when the request names no card")
    _check_template(catalog, _card(catalog, chosen).fills.layout)
    check_catalog_ids(out.values, catalog)
    check_theme_id(out.values, catalog, current_art_style)


def _scene_count(card: FormatCard, target_duration_s: int) -> int:
    counts = card.recommends.scene_count
    return getattr(counts, _SCENE_COUNT_FIELDS[target_duration_s])


def _card_patches(
    card: FormatCard,
    *,
    requested_card: str | None,
    target_duration_s: int,
    catalog: CatalogPort,
) -> list[ValuePatch]:
    layout = catalog.pin("template", card.fills.layout).model_dump(mode="json")
    card_id_origin = Origin.user if requested_card else Origin.llm
    return [
        ValuePatch(
            path="/settings/format/card_id", value=card.id, origin=card_id_origin
        ),
        ValuePatch(
            path="/settings/format/story_structure",
            value=card.fills.story_structure,
            origin=Origin.card,
        ),
        ValuePatch(path="/settings/format/layout", value=layout, origin=Origin.card),
        ValuePatch(
            path="/settings/format/character_role",
            value=card.fills.character_role.value,
            origin=Origin.card,
        ),
        ValuePatch(
            path="/settings/format/register",
            value=card.fills.register_value.value,
            origin=Origin.card,
        ),
        ValuePatch(path="/settings/format/humor", value=card.fills.humor.value, origin=Origin.card),
        ValuePatch(
            path="/settings/format/progress_mode",
            value=card.recommends.progress_mode.value,
            origin=Origin.card,
        ),
        ValuePatch(
            path="/settings/format/scene_count",
            value=_scene_count(card, target_duration_s),
            origin=Origin.card,
        ),
        ValuePatch(
            path="/settings/caption/mode",
            value=card.recommends.caption_mode.value,
            origin=Origin.card,
        ),
        ValuePatch(
            path="/settings/audio/bgm/mood",
            value=card.recommends.bgm_mood.value,
            origin=Origin.card,
        ),
    ]


def _effective_brief(video: Video, ops: list[Op], topic: str) -> ScriptBrief:
    settings = video.settings
    language = settings.language
    duration = settings.target_duration_s
    story_structure = settings.format.story_structure
    register = settings.format.register_value
    humor = settings.format.humor
    scene_count = settings.format.scene_count
    for op in ops:
        if op.op != "set":
            continue
        if op.path == "/settings/language":
            language = Language(op.value)
        elif op.path == "/settings/target_duration_s":
            duration = int(op.value)
        elif op.path == "/settings/format/story_structure":
            story_structure = str(op.value)
        elif op.path == "/settings/format/register":
            register = Register(op.value)
        elif op.path == "/settings/format/humor":
            humor = Humor(op.value)
        elif op.path == "/settings/format/scene_count":
            scene_count = int(op.value)
    return ScriptBrief(
        language=language,
        story_structure=story_structure,
        register=register,
        humor=humor,
        target_duration_s=duration,
        scene_count=scene_count,
        topic=topic,
    )


def draft(
    video: Video,
    message: str,
    card_id: str | None,
    *,
    llm: LlmPort,
    catalog: CatalogPort,
    ctx: JobContext,
) -> list[Op]:
    """Fill every stage from one sentence and return the patches for it."""
    data = {
        "message": message,
        "language": video.settings.language.value,
        "target_duration_s": video.settings.target_duration_s,
        "card_id": card_id,
        "topic": video.topic,
    }
    out = complete_json(
        llm,
        task=LlmTask.draft,
        route=DRAFT_ROUTE,
        model=DraftOutput,
        data=data,
        max_output_tokens=DRAFT_MAX_TOKENS,
        ctx=ctx,
        check=lambda value: _check_draft(
            value,
            requested_card=card_id,
            catalog=catalog,
            current_art_style=video.settings.visual.art_style.id,
        ),
    )
    chosen = card_id or out.card_id
    if chosen is None:
        raise AppError("llm_invalid_output", detail={"task": LlmTask.draft.value})
    card = _card(catalog, chosen)
    duration = out.values.target_duration_s or video.settings.target_duration_s
    patches: list[ValuePatch] = [
        ValuePatch(path="/topic", value=out.topic, origin=Origin.user)
    ]
    patches.extend(
        _card_patches(
            card, requested_card=card_id, target_duration_s=duration, catalog=catalog
        )
    )
    patches.extend(
        field_patches(
            out.values,
            catalog=catalog,
            origin=Origin.llm,
            evidence=out.evidence,
            message=message,
        )
    )
    outcome = build_ops(video, patches)
    ops: list[Op] = list(outcome.ops)
    if video.script is None:
        brief = _effective_brief(video, ops, out.topic)
        ops.extend(build_script_ops(video, brief, llm=llm, catalog=catalog, ctx=ctx))
    return ops


__all__ = ["DRAFT_ROUTE", "DraftOutput", "draft"]
