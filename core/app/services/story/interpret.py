"""Chat interpretation: one sentence becomes typed value patches.

Chat changes values, never the script text: an instruction about one scene is
answered by the scene rewrite route instead. Values the request cannot reach,
locked keys and values outside the target come back as unsupported so the UI can
say which part it could not do.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from app.ports import CatalogPort, JobContext, LlmPort, LlmTask, Proposal
from app.schemas.change import Target
from app.schemas.common import ContractModel, Language, Origin
from app.schemas.job import Stage
from app.schemas.settings import Settings
from app.schemas.video import Video
from app.services.story.patch import (
    SettingsValues,
    SkipReason,
    ValuePatch,
    build_ops,
    check_catalog_ids,
    check_theme_id,
    complete_json,
    field_patches,
    llm_step,
)

CHAT_ROUTE = "chat"
CHAT_MAX_TOKENS = 1000
EXTRA_INSTRUCTIONS_PATH = "/settings/extra_instructions"
MAX_EXTRA_INSTRUCTIONS = 20
EMPTY_MESSAGE = {
    Language.ko: "무엇을 바꿀지 한 문장으로 알려 주세요.",
    Language.en: "Tell me in one sentence what to change.",
}

_REFUSAL_HINT = {
    SkipReason.locked: {
        Language.ko: "잠긴 값이에요. 설정에서 잠금을 풀고 다시 요청해 주세요.",
        Language.en: "This value is locked. Unlock it in settings and ask again.",
    },
    SkipReason.outside_target: {
        Language.ko: "현재 대상에 없는 값이에요. 대상 칩을 지우고 다시 요청해 주세요.",
        Language.en: "This value is outside the current target. Clear the target and ask again.",
    },
    SkipReason.lower_origin: {
        Language.ko: "직접 고른 값을 보존했어요. 설정에서 그 값을 직접 바꿔 주세요.",
        Language.en: "Your prior choice was kept. Change it directly in settings.",
    },
}


class ChatOutput(ContractModel):
    """Model output of the chat route. Values, notes and refusals only."""

    values: SettingsValues = Field(default_factory=SettingsValues)
    extra_instructions: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=5)
    ] = Field(default_factory=list)
    notes: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=300)]], Field(max_length=5)
    ] = Field(default_factory=list)
    unsupported: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=10)
    ] = Field(default_factory=list)
    question: Annotated[str, Field(min_length=1, max_length=300)] | None = None


def _settings_data(settings: Settings) -> dict[str, Any]:
    return {
        "language": settings.language.value,
        "target_duration_s": settings.target_duration_s,
        "format": {
            "card_id": settings.format.card_id,
            "story_structure": settings.format.story_structure,
            "layout": settings.format.layout.id,
            "character_role": settings.format.character_role.value,
            "register": settings.format.register_value.value,
            "humor": settings.format.humor.value,
            "progress_mode": settings.format.progress_mode.value,
            "scene_count": settings.format.scene_count,
        },
        "visual": {
            "art_style": settings.visual.art_style.id,
            "theme_id": settings.visual.theme_id,
            "character": settings.visual.character is not None,
        },
        "audio": {
            "voice": settings.audio.voice.id,
            "bgm": {"enabled": settings.audio.bgm.enabled, "mood": settings.audio.bgm.mood.value},
            "sfx_enabled": settings.audio.sfx_enabled,
        },
        "caption": {
            "mode": settings.caption.mode.value,
            "position": settings.caption.position.value,
            "highlight": settings.caption.highlight,
        },
        "motion": {
            "transition": settings.motion.transition.value,
            "character_motion": settings.motion.character_motion.value,
        },
        "locks": {key.value: state.value for key, state in settings.locks.items()},
    }


def _scenes_data(video: Video) -> list[dict[str, Any]]:
    return [
        {
            "scene_id": scene_id,
            "beat_label": video.scenes[scene_id].beat_label,
            "lines": [line.display_text for line in video.scenes[scene_id].lines],
        }
        for scene_id in video.scene_order
    ]


def _merged_instructions(
    existing: list[str], proposed: list[str]
) -> tuple[list[str], list[str]]:
    merged = list(dict.fromkeys([*existing, *(item.strip() for item in proposed if item.strip())]))
    return merged[:MAX_EXTRA_INSTRUCTIONS], merged[MAX_EXTRA_INSTRUCTIONS:]


def _check_chat(out: ChatOutput, catalog: CatalogPort, current_art_style: str) -> None:
    check_catalog_ids(out.values, catalog)
    check_theme_id(out.values, catalog, current_art_style)


def interpret(
    video: Video,
    text: str,
    target: Target,
    *,
    llm: LlmPort,
    catalog: CatalogPort,
    ctx: JobContext,
) -> Proposal:
    """Turn one chat sentence into value patches within the request target."""
    language = video.settings.language
    if not text.strip():
        return Proposal(ops=[], notes=[EMPTY_MESSAGE[language]], unsupported=[])
    data = {
        "message": text,
        "target": {"scene_id": target.scene_id, "pointer": target.pointer},
        "language": language.value,
        "settings": _settings_data(video.settings),
        "scenes": _scenes_data(video),
        "extra_instructions": list(video.settings.extra_instructions),
    }
    out = llm_step(
        ctx,
        Stage.llm_chat,
        done=0,
        total=1,
        call=lambda: complete_json(
            llm,
            task=LlmTask.chat,
            route=CHAT_ROUTE,
            model=ChatOutput,
            data=data,
            max_output_tokens=CHAT_MAX_TOKENS,
            ctx=ctx,
            check=lambda value: _check_chat(
                value, catalog, video.settings.visual.art_style.id
            ),
        ),
    )
    if out.question:
        return Proposal(ops=[], notes=[out.question], unsupported=[])
    patches: list[ValuePatch] = field_patches(
        out.values, catalog=catalog, origin=Origin.user
    )
    unsupported = list(out.unsupported)
    if out.extra_instructions:
        merged, dropped = _merged_instructions(
            list(video.settings.extra_instructions), out.extra_instructions
        )
        if merged != list(video.settings.extra_instructions):
            patches.append(
                ValuePatch(
                    path=EXTRA_INSTRUCTIONS_PATH, value=merged, origin=Origin.user
                )
            )
        unsupported = [
            (
                f"추가 지시가 가득 차서 저장하지 않았어요: {item[:100]}. "
                "기존 지시를 정리하고 다시 요청해 주세요."
                if language is Language.ko
                else f"No room to save this instruction: {item[:100]}. "
                "Remove a saved instruction and ask again."
            )
            for item in dropped
        ] + unsupported
    outcome = build_ops(video, patches, target=target)
    notes = list(out.notes)
    unsupported.extend(
        f"{path}: {_REFUSAL_HINT[reason][language]}" for path, reason in outcome.skipped
    )
    return Proposal(ops=list(outcome.ops), notes=notes[:5], unsupported=unsupported[:10])


__all__ = ["CHAT_ROUTE", "ChatOutput", "interpret"]
