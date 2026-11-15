"""Rewrite one scene and report neighbor text that still uses the old wording.

The rewrite returns ops on the target scene's lines and, only when a reference
broke, on its visual. Lines whose text did not change keep their id, highlight
spans and references wherever they moved in the list; every other visual
reference is repointed or dropped inside that scene. Neighbor text is only
inspected for a warning; it is never edited.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field

from app.ports import (
    AppError,
    JobContext,
    LlmPart,
    LlmPort,
    LlmTask,
    canonical_json,
)
from app.schemas.change import Op, PlanWarning, ReplaceSceneOp, SetOp, WarningCode
from app.schemas.common import ContractModel, EntityId, Origin
from app.schemas.job import Stage, WaitingOn
from app.schemas.scene import Element, Scene, SceneVisual, SfxCue
from app.schemas.script import Line, Span, Speaker
from app.schemas.video import Video
from app.services.story.scene_data import ask_json, new_entity_id

SCENE_REWRITE_MAX_TOKENS = 800

_LINES_PATH = re.compile(r"^/scenes/([^/]+)/lines$")
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_HANGUL_SUFFIXES = (
    "에서는",
    "으로는",
    "에서",
    "으로",
    "까지",
    "부터",
    "처럼",
    "보다",
    "라고",
    "라는",
    "에게",
    "한테",
    "에는",
    "에도",
    "만큼",
    "조차",
    "마저",
    "이나",
    "라도",
    "을",
    "를",
    "이",
    "가",
    "은",
    "는",
    "의",
    "에",
    "와",
    "과",
    "도",
    "만",
    "로",
)
_ASCII_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "your",
        "you",
        "are",
        "was",
        "were",
        "not",
        "but",
        "its",
        "our",
        "their",
        "have",
        "has",
        "had",
        "can",
        "will",
        "just",
        "then",
        "than",
        "they",
        "them",
        "there",
        "here",
        "when",
        "what",
        "which",
        "who",
        "how",
        "all",
        "one",
        "two",
        "three",
    }
)


class LineChoice(ContractModel):
    display_text: Annotated[str, Field(min_length=1, max_length=300)]
    speech_text: Annotated[str, Field(min_length=1, max_length=500)]
    speaker: Speaker


class SceneRewriteResponse(ContractModel):
    scene_id: EntityId
    lines: Annotated[list[LineChoice], Field(min_length=1, max_length=4)]


@dataclass(frozen=True)
class SceneRewrite:
    """Ops for the target scene plus warning candidates for the plan."""

    scene_id: str
    ops: list[Op]
    warnings: list[PlanWarning]


def plan_scene_rewrite(
    video: Video,
    scene_id: str,
    instruction: str,
    *,
    llm: LlmPort,
    ctx: JobContext,
) -> SceneRewrite:
    """Rewrite the lines of one scene; the returned op keeps id and order."""
    scene = video.scenes.get(scene_id)
    if scene is None:
        raise AppError("validation_failed", detail={"unknown_scene_ids": [scene_id]})
    with ctx.stage(Stage.llm_chat):
        ctx.progress(done=0, total=1, waiting_on=WaitingOn.llm)
        response = ask_json(
            route="scene_rewrite",
            task=LlmTask.scene_rewrite,
            schema_model=SceneRewriteResponse,
            parts=_rewrite_parts(video, scene, instruction),
            validate=lambda item: _rewrite_problems(item, scene),
            llm=llm,
            ctx=ctx,
            max_output_tokens=SCENE_REWRITE_MAX_TOKENS,
        )
        ctx.progress(done=1, total=1)
    rewrite = _rewrite_lines(scene, response.lines)
    ops: list[Op] = [
        SetOp(
            op="set",
            path=f"/scenes/{scene.id}/lines",
            value=[line.model_dump(mode="json") for line in rewrite.lines],
            origin=Origin.llm,
        )
    ]
    visual = _cleaned_visual(scene, rewrite)
    if visual is not None:
        ops.append(
            SetOp(
                op="set",
                path=f"/scenes/{scene.id}/visual",
                value=visual.model_dump(mode="json"),
                origin=Origin.llm,
            )
        )
    return SceneRewrite(
        scene_id=scene.id,
        ops=ops,
        warnings=stale_wording_warnings(video, ops),
    )


def _rewrite_parts(video: Video, scene: Scene, instruction: str) -> list[LlmPart]:
    payload = {
        "language": video.settings.language.value,
        "register": video.settings.format.register_value.value,
        "humor": video.settings.format.humor.value,
        "instruction": instruction,
        "scene": {
            "id": scene.id,
            "beat_id": scene.beat_id,
            "beat_label": scene.beat_label,
            "lines": [
                {
                    "id": line.id,
                    "display_text": line.display_text,
                    "speech_text": line.speech_text,
                    "speaker": line.speaker.value,
                }
                for line in scene.lines
            ],
        },
    }
    return [LlmPart(kind="text", text=canonical_json(payload).decode("utf-8"))]


def _rewrite_problems(response: SceneRewriteResponse, scene: Scene) -> list[str]:
    problems: list[str] = []
    if response.scene_id != scene.id:
        problems.append(f"scene_id must stay {scene.id}")
    return problems


@dataclass(frozen=True)
class _LineRewrite:
    lines: list[Line]
    # Old line id to a fresh line at the same position, or None when there is none.
    replacement: dict[str, str | None]


def _rewrite_lines(scene: Scene, choices: list[LineChoice]) -> _LineRewrite:
    """Keep every line whose text did not change, then issue ids for the rest.

    Matching runs across the whole old list so that removing an earlier line
    does not renumber the lines that stay. A kept line keeps its id, its
    highlight spans and every reference to it.
    """
    sources: list[Line | None] = [None] * len(choices)
    used: set[int] = set()
    for index, choice in enumerate(choices):
        if index < len(scene.lines) and _same_text(scene.lines[index], choice):
            sources[index] = scene.lines[index]
            used.add(index)
    for index, choice in enumerate(choices):
        if sources[index] is not None:
            continue
        for old_index, old in enumerate(scene.lines):
            if old_index not in used and _same_text(old, choice):
                sources[index] = old
                used.add(old_index)
                break
    lines = [
        Line(
            id=source.id if source is not None else new_entity_id("l"),
            display_text=choice.display_text,
            speech_text=choice.speech_text,
            speaker=choice.speaker,
            highlight=_kept_highlight(scene, choice, source),
        )
        for choice, source in zip(choices, sources, strict=True)
    ]
    fresh = {index for index, source in enumerate(sources) if source is None}
    preserved = {line.id for line in lines}
    replacement = {
        old.id: (lines[index].id if index in fresh else None)
        for index, old in enumerate(scene.lines)
        if old.id not in preserved
    }
    return _LineRewrite(lines=lines, replacement=replacement)


def _same_text(old: Line, choice: LineChoice) -> bool:
    return (
        old.display_text == choice.display_text
        and old.speech_text == choice.speech_text
    )


def _kept_highlight(
    scene: Scene, choice: LineChoice, source: Line | None
) -> list[Span]:
    """Spans a line keeps: its own when matched, else those of the same display text.

    A span addresses characters of `display_text`, so it stays valid when only
    the spoken text changes.
    """
    if source is not None:
        return list(source.highlight)
    twin = next(
        (old for old in scene.lines if old.display_text == choice.display_text), None
    )
    return list(twin.highlight) if twin is not None else []


def _cleaned_visual(scene: Scene, rewrite: _LineRewrite) -> SceneVisual | None:
    """Repoint or drop visual references that the new line list broke.

    A reference to a removed line moves to a fresh line at the same position
    when one exists, so a cue keeps its place in the scene; otherwise the
    reference is dropped.
    """
    visual = scene.visual
    if visual is None:
        return None
    line_ids = {line.id for line in rewrite.lines}
    changed = False
    elements: list[Element] = []
    for element in visual.elements:
        reveal = element.reveal_line_id
        if reveal is None or reveal in line_ids:
            elements.append(element)
            continue
        changed = True
        elements.append(
            element.model_copy(update={"reveal_line_id": rewrite.replacement.get(reveal)})
        )
    sfx: list[SfxCue] = []
    for cue in visual.sfx:
        if cue.line_id in line_ids:
            sfx.append(cue)
            continue
        changed = True
        target = rewrite.replacement.get(cue.line_id)
        if target is not None:
            sfx.append(cue.model_copy(update={"line_id": target}))
    if not changed:
        return None
    return visual.model_copy(update={"elements": elements, "sfx": sfx})


def stale_wording_warnings(video: Video, ops: Sequence[Op]) -> list[PlanWarning]:
    """Neighbors that still carry a term the rewritten scene dropped."""
    warnings: list[PlanWarning] = []
    marked: set[str] = set()
    for scene_id, texts in _rewritten_scenes(ops):
        if scene_id not in video.scenes or scene_id not in video.scene_order:
            continue
        dropped = _terms(_scene_text(video.scenes[scene_id])) - _terms(" ".join(texts))
        if not dropped:
            continue
        position = video.scene_order.index(scene_id)
        for neighbor_id in _neighbors(video.scene_order, position):
            if neighbor_id in marked:
                continue
            if dropped & _terms(_scene_text(video.scenes[neighbor_id])):
                warnings.append(
                    PlanWarning(
                        code=WarningCode.stale_wording_in_neighbor,
                        scene_id=neighbor_id,
                    )
                )
                marked.add(neighbor_id)
    return warnings


def _rewritten_scenes(ops: Sequence[Op]) -> Iterator[tuple[str, list[str]]]:
    for op in ops:
        if isinstance(op, SetOp):
            match = _LINES_PATH.fullmatch(op.path)
            if match is not None:
                yield match.group(1), _line_texts(op.value)
        elif isinstance(op, ReplaceSceneOp):
            yield op.scene.id, [line.display_text for line in op.scene.lines]


def _line_texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    texts: list[str] = []
    for item in value:
        if isinstance(item, dict):
            texts.extend(
                str(item[key]) for key in ("display_text", "speech_text") if key in item
            )
        else:
            texts.append(str(item))
    return texts


def _scene_text(scene: Scene) -> str:
    return " ".join(
        f"{line.display_text} {line.speech_text}" for line in scene.lines
    )


def _neighbors(order: Sequence[str], position: int) -> list[str]:
    found = []
    if position > 0:
        found.append(order[position - 1])
    if position + 1 < len(order):
        found.append(order[position + 1])
    return found


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for raw in _TOKEN.findall(text):
        if raw.isascii():
            lowered = raw.lower()
            if len(lowered) >= 3 and lowered not in _ASCII_STOP:
                terms.add(lowered)
        elif len(raw) >= 2:
            terms.add(_stem(raw))
    return terms


def _stem(term: str) -> str:
    for suffix in _HANGUL_SUFFIXES:
        if term.endswith(suffix) and len(term) - len(suffix) >= 2:
            return term[: -len(suffix)]
    return term


__all__ = ["SceneRewrite", "plan_scene_rewrite", "stale_wording_warnings"]
