"""Script routes: write a script, then split it into scenes.

The script route depends on the story structure: ``script.numbered_three`` and
``script.default`` are separate files, so the numbered flow never shares text
with the analogy and hypothetical flows. The split route only groups numbered
lines, so a script the user supplied keeps every sentence byte for byte.
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field

from app.ports import AppError, CatalogPort, JobContext, LlmPort, LlmTask
from app.schemas.change import Op, SetScriptOp
from app.schemas.common import ContractModel, Language, LocalizedText
from app.schemas.format_card import StoryStructure
from app.schemas.job import Stage
from app.schemas.scene import Line, Scene
from app.schemas.script import Script, ScriptSource, Span, Speaker
from app.schemas.settings import Humor, Register
from app.schemas.video import Video
from app.services.story.patch import complete_json, llm_step

NUMBERED_THREE = "numbered_three"
SCRIPT_NUMBERED_ROUTE = "script.numbered_three"
SCRIPT_DEFAULT_ROUTE = "script.default"
SPLIT_ROUTE = "split"
SCRIPT_MAX_TOKENS = 2400
SPLIT_MAX_TOKENS = 1200
MAX_LINE_DISPLAY = 300
MAX_SCENE_LINES = 4

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_SENTENCE_BREAK = re.compile(r"(?<=[.!?。？！])\s+|\n+")


def script_route(story_structure: str) -> str:
    return SCRIPT_NUMBERED_ROUTE if story_structure == NUMBERED_THREE else SCRIPT_DEFAULT_ROUTE


def _new_id(prefix: str) -> str:
    """App-style TypeID: UUIDv7 bits in lower case Crockford base32."""
    timestamp_ms = time.time_ns() // 1_000_000
    random_bits = secrets.randbits(74)
    raw = bytearray(timestamp_ms.to_bytes(6, "big"))
    raw += (0x7000 | (random_bits >> 62)).to_bytes(2, "big")
    raw += (0x8000_0000_0000_0000 | (random_bits & ((1 << 62) - 1))).to_bytes(8, "big")
    value = int.from_bytes(raw, "big")
    encoded = "".join(_ALPHABET[(value >> shift) & 31] for shift in range(125, -1, -5))
    return f"{prefix}_{encoded}"


def split_sentences(text: str) -> list[str]:
    """Split on sentence punctuation followed by space and on blank lines."""
    chunks: list[str] = []
    for part in _SENTENCE_BREAK.split(text):
        stripped = part.strip()
        if not stripped:
            continue
        chunks.extend(_bounded(stripped))
    return chunks


def _bounded(text: str) -> list[str]:
    if len(text) <= MAX_LINE_DISPLAY:
        return [text]
    pieces: list[str] = []
    rest = text
    while len(rest) > MAX_LINE_DISPLAY:
        cut = rest.rfind(" ", 0, MAX_LINE_DISPLAY + 1)
        if cut <= 0:
            cut = MAX_LINE_DISPLAY
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return [piece for piece in pieces if piece]


@dataclass(frozen=True)
class ScriptBrief:
    """Inputs of the script routes, taken from settings or a draft in progress."""

    language: Language
    story_structure: str
    register: Register
    humor: Humor
    target_duration_s: int
    scene_count: int
    topic: str


class ScriptLineOut(ContractModel):
    display_text: Annotated[str, Field(min_length=1, max_length=MAX_LINE_DISPLAY)]
    speech_text: Annotated[str, Field(min_length=1, max_length=500)]
    highlight: Annotated[list[str], Field(max_length=4)] = Field(default_factory=list)


class ScriptBeatOut(ContractModel):
    beat_id: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,24}$")]
    lines: Annotated[list[ScriptLineOut], Field(min_length=1, max_length=6)]


class ScriptOutput(ContractModel):
    title: Annotated[str, Field(min_length=1, max_length=80)]
    beats: Annotated[list[ScriptBeatOut], Field(min_length=2, max_length=12)]


class SplitSceneOut(ContractModel):
    beat_id: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,24}$")]
    beat_label: Annotated[str, Field(min_length=1, max_length=40)]
    line_indices: Annotated[list[int], Field(min_length=1, max_length=MAX_SCENE_LINES)]


class SplitOutput(ContractModel):
    scenes: Annotated[list[SplitSceneOut], Field(min_length=1, max_length=30)]


def _label(label: LocalizedText, language: Language) -> str:
    return label.ko if language is Language.ko else label.en


def _structure(catalog: CatalogPort, story_structure: str) -> StoryStructure:
    manifest = catalog.get("story_structure", story_structure)
    if not isinstance(manifest, StoryStructure):
        raise AppError("internal", detail={"story_structure": story_structure})
    return manifest


def _beats(structure: StoryStructure, language: Language) -> list[tuple[str, str]]:
    return [(beat.beat_id, _label(beat.label, language)) for beat in structure.beats]


def _check_script(out: ScriptOutput, structure: StoryStructure) -> None:
    expected = [beat.beat_id for beat in structure.beats]
    actual = [beat.beat_id for beat in out.beats]
    if actual != expected:
        raise ValueError(f"beats must be exactly {expected} in order, got {actual}")


def _check_split(
    out: SplitOutput,
    structure: StoryStructure,
    line_count: int,
    line_beats: list[str | None],
) -> None:
    ranks = {beat.beat_id: index for index, beat in enumerate(structure.beats)}
    indices: list[int] = []
    ranks_seen: list[int] = []
    for scene in out.scenes:
        if scene.beat_id not in ranks:
            raise ValueError(f"unknown beat_id {scene.beat_id}")
        for index in scene.line_indices:
            if index < 0 or index >= line_count:
                raise ValueError(f"line index {index} is outside 0..{line_count - 1}")
        original = {line_beats[index] for index in scene.line_indices}
        original.discard(None)
        if original and original != {scene.beat_id}:
            raise ValueError(
                f"scene beat {scene.beat_id} does not match its lines {sorted(original)}"
            )
        ranks_seen.append(ranks[scene.beat_id])
        indices.extend(scene.line_indices)
    if indices != list(range(line_count)):
        raise ValueError(
            f"line indices must cover 0..{line_count - 1} once in order, got {indices}"
        )
    if ranks_seen != sorted(ranks_seen):
        raise ValueError(f"scenes must follow the story structure order, got {ranks_seen}")


def _script_data(
    video: Video, brief: ScriptBrief, beat_ids: list[str]
) -> dict[str, object]:
    return {
        "language": brief.language.value,
        "story_structure": brief.story_structure,
        "register": brief.register.value,
        "humor": brief.humor.value,
        "target_duration_s": brief.target_duration_s,
        "scene_count": brief.scene_count,
        "topic": brief.topic,
        "material": [material.text for material in video.material],
        "extra_instructions": list(video.settings.extra_instructions),
        "beat_ids": beat_ids,
    }


def _split_data(
    brief: ScriptBrief,
    beats: list[tuple[str, str]],
    lines: list[ScriptLineOut],
    line_beats: list[str | None],
) -> dict[str, object]:
    return {
        "language": brief.language.value,
        "story_structure": brief.story_structure,
        "beats": [{"beat_id": beat_id, "label": label} for beat_id, label in beats],
        "numbered_lines": [
            {"index": index, "text": line.display_text, "beat_id": line_beats[index]}
            for index, line in enumerate(lines)
        ],
        "scene_count": brief.scene_count,
        "target_duration_s": brief.target_duration_s,
    }


def _split(
    brief: ScriptBrief,
    beats: list[tuple[str, str]],
    lines: list[ScriptLineOut],
    line_beats: list[str | None],
    structure: StoryStructure,
    llm: LlmPort,
    ctx: JobContext,
    done: int,
    total: int,
) -> SplitOutput:
    return llm_step(
        ctx,
        Stage.llm_split,
        done=done,
        total=total,
        call=lambda: complete_json(
            llm,
            task=LlmTask.split,
            route=SPLIT_ROUTE,
            model=SplitOutput,
            data=_split_data(brief, beats, lines, line_beats),
            max_output_tokens=SPLIT_MAX_TOKENS,
            ctx=ctx,
            check=lambda value: _check_split(value, structure, len(lines), line_beats),
        ),
    )


def _spans(text: str, keywords: list[str]) -> list[Span]:
    spans: list[Span] = []
    for keyword in keywords:
        if not keyword:
            continue
        start = text.find(keyword)
        if start < 0:
            continue
        end = start + len(keyword)
        if spans and start < spans[-1].end:
            continue
        spans.append(Span(start=start, end=end))
    return spans[:4]


def _line(source: ScriptLineOut) -> Line:
    return Line(
        id=_new_id("l"),
        display_text=source.display_text,
        speech_text=source.speech_text,
        speaker=Speaker.narrator,
        highlight=_spans(source.display_text, source.highlight),
    )


def _scenes(split: SplitOutput, lines: list[ScriptLineOut]) -> list[Scene]:
    scenes: list[Scene] = []
    for group in split.scenes:
        scenes.append(
            Scene(
                id=_new_id("s"),
                beat_id=group.beat_id,
                beat_label=group.beat_label,
                lines=[_line(lines[index]) for index in group.line_indices],
                visual=None,
            )
        )
    return scenes


def _user_script(video: Video) -> Script | None:
    script = video.script
    if script is not None and script.source is ScriptSource.user and script.raw_text:
        return script
    return None


def _verbatim_lines(script: Script) -> list[ScriptLineOut]:
    return [
        ScriptLineOut(display_text=sentence, speech_text=sentence)
        for sentence in split_sentences(script.raw_text or "")
    ]


def _generated_lines(out: ScriptOutput) -> list[ScriptLineOut]:
    return [line for beat in out.beats for line in beat.lines]


def script_steps(video: Video) -> int:
    """LLM calls `build_script_ops` makes: the split, and a script unless the user wrote one."""
    return 1 if _user_script(video) is not None else 2


def build_script_ops(
    video: Video,
    brief: ScriptBrief,
    *,
    llm: LlmPort,
    catalog: CatalogPort,
    ctx: JobContext,
    steps_done: int = 0,
    steps_total: int | None = None,
) -> list[Op]:
    """Write or split a script and return the one op that stores it.

    Progress counts the LLM calls of the job: a caller that ran calls before this one
    passes how many are done and the job's total.
    """
    total = steps_total if steps_total is not None else steps_done + script_steps(video)
    structure = _structure(catalog, brief.story_structure)
    beats = _beats(structure, brief.language)
    script = _user_script(video)
    if script is not None:
        lines = _verbatim_lines(script)
        line_beats: list[str | None] = [None] * len(lines)
        source = Script(source=ScriptSource.user, raw_text=script.raw_text, title=script.title)
    else:
        out = llm_step(
            ctx,
            Stage.llm_script,
            done=steps_done,
            total=total,
            call=lambda: complete_json(
                llm,
                task=LlmTask.script,
                route=script_route(brief.story_structure),
                model=ScriptOutput,
                data=_script_data(video, brief, [beat_id for beat_id, _ in beats]),
                max_output_tokens=SCRIPT_MAX_TOKENS,
                ctx=ctx,
                check=lambda value: _check_script(value, structure),
            ),
        )
        steps_done += 1
        lines = _generated_lines(out)
        line_beats = [beat.beat_id for beat in out.beats for _ in beat.lines]
        source = Script(
            source=ScriptSource.llm,
            raw_text="\n".join(line.display_text for line in lines),
            title=out.title,
        )
    if not lines:
        raise AppError("llm_invalid_output", detail={"task": LlmTask.script.value})
    split = _split(brief, beats, lines, line_beats, structure, llm, ctx, steps_done, total)
    return [SetScriptOp(op="set_script", script=source, scenes=_scenes(split, lines))]


def brief_from_video(video: Video) -> ScriptBrief:
    settings = video.settings
    return ScriptBrief(
        language=settings.language,
        story_structure=settings.format.story_structure,
        register=settings.format.register_value,
        humor=settings.format.humor,
        target_duration_s=settings.target_duration_s,
        scene_count=settings.format.scene_count,
        topic=video.topic,
    )


def write_script(
    video: Video, *, llm: LlmPort, catalog: CatalogPort, ctx: JobContext
) -> list[Op]:
    return build_script_ops(video, brief_from_video(video), llm=llm, catalog=catalog, ctx=ctx)


__all__ = [
    "SCRIPT_DEFAULT_ROUTE",
    "SCRIPT_NUMBERED_ROUTE",
    "SPLIT_ROUTE",
    "ScriptBrief",
    "build_script_ops",
    "brief_from_video",
    "script_route",
    "script_steps",
    "split_sentences",
    "write_script",
]
