"""The ``reference_vision`` route: frames and a transcript in, closed format values out.

The model answers with catalog ids, enum values and colours only. It writes no
free text, so nothing a reference video says can reach a plan note or a prompt of
another route. The system prompt is the trusted body of ``prompts/<route>/prompt.md``;
the frames travel as ``png`` data parts and the transcript as one text part.
Only frames and the transcript leave the machine (CONTRACTS 10.4).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import ConfigDict, Field, ValidationError

from app.ports import AppError, JobContext, LlmPart, LlmPort, LlmRequest, LlmResult, LlmTask
from app.schemas.common import (
    HEX_COLOR_PATTERN,
    CaptionMode,
    CatalogId,
    CharacterRole,
    ContractModel,
    Mood,
)
from app.schemas.job import Stage
from app.schemas.settings import Humor, ProgressMode, Register
from app.schemas.video import CaptionBoxDescription

ROUTE = "reference_vision"
PROMPT_ROOT = Path(__file__).resolve().parent / "prompts"
MAX_FRAMES = 8
"""Frames per call (CONTRACTS 10.1)."""

MAX_TRANSCRIPT_CHARS = 6000
MAX_OUTPUT_TOKENS = 600
REPAIR_NOTE = "\n\n# Repair\n\nReturn corrected JSON that validates against the schema.\n"


class CaptionPlaceRatios(ContractModel):
    """Where the reference video puts its caption plate, as ratios of the frame.

    Ratios rather than pixels: reference videos have different resolutions, and
    the app maps these onto the 1080x1920 frame. A value outside 0 to 1, or a
    plate with no width or height, is dropped before it becomes a place.
    """

    y_top: float
    y_bottom: float
    x_left: float
    x_right: float
    align: Literal["left", "center", "right"] | None = None


class ReferenceValues(ContractModel):
    """What the model may say about a reference video. ``None`` means it cannot tell."""

    story_structure: CatalogId | None = None
    layout: CatalogId | None = None
    character_role: CharacterRole | None = None
    register_value: Annotated[Register | None, Field(alias="register")] = None
    humor: Humor | None = None
    progress_mode: ProgressMode | None = None
    caption_mode: CaptionMode | None = None
    caption_place: CaptionPlaceRatios | None = None
    caption_box: CaptionBoxDescription | None = None
    bgm_mood: Mood | None = None
    palette: Annotated[
        list[Annotated[str, Field(pattern=HEX_COLOR_PATTERN)]], Field(max_length=5)
    ] = Field(default_factory=list)
    # One-based positions of the sent frames that show the character or subject.
    subject_frames: Annotated[
        list[Annotated[int, Field(ge=1, le=MAX_FRAMES)]], Field(max_length=MAX_FRAMES)
    ] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("prompt is missing front matter")
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        raise ValueError("prompt front matter is not closed")
    matter = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(matter, dict):
        raise ValueError("prompt front matter is not a mapping")
    return matter, "\n".join(lines[end + 1 :]).strip()


def load_prompt(data: Mapping[str, Any]) -> str:
    """The trusted system body; the declared data variables must match what is sent."""
    path = PROMPT_ROOT / ROUTE / "prompt.md"
    if not path.is_file():
        raise AppError("internal", detail={"prompt": ROUTE, "problem": "missing"})
    try:
        matter, body = _split_front_matter(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise AppError("internal", detail={"prompt": ROUTE, "problem": "front_matter"}) from error
    declared = matter.get("data_variables")
    version = matter.get("version")
    if matter.get("route") != ROUTE:
        raise AppError("internal", detail={"prompt": ROUTE, "problem": "route"})
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise AppError("internal", detail={"prompt": ROUTE, "problem": "version"})
    if not isinstance(declared, list) or set(declared) != set(data):
        raise AppError("internal", detail={"prompt": ROUTE, "problem": "variables"})
    if not body:
        raise AppError("internal", detail={"prompt": ROUTE, "problem": "body"})
    return body + "\n"


def _without_caption_box(result: LlmResult) -> ReferenceValues:
    if result.parsed is None:
        raise ValueError("output is not a JSON object")
    return ReferenceValues.model_validate(
        {key: value for key, value in result.parsed.items() if key != "caption_box"}
    )


def _caption_box(result: LlmResult) -> CaptionBoxDescription | None:
    if result.parsed is None:
        raise ValueError("output is not a JSON object")
    box = result.parsed.get("caption_box")
    return None if box is None else CaptionBoxDescription.model_validate(box)


def ask(
    llm: LlmPort,
    *,
    frames: list[bytes],
    transcript: str,
    allowed: Mapping[str, list[str]],
    ctx: JobContext,
) -> ReferenceValues:
    """Repair once; a malformed box must not erase valid analysis fields."""
    if not frames or len(frames) > MAX_FRAMES:
        raise ValueError(f"send 1 to {MAX_FRAMES} frames")
    data = {"transcript": transcript[:MAX_TRANSCRIPT_CHARS], "allowed": dict(allowed)}
    system = load_prompt(data)
    parts = [
        *(LlmPart(kind="png", png=frame) for frame in frames),
        LlmPart(
            kind="text", text=json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)
        ),
    ]
    schema = ReferenceValues.model_json_schema()
    # Let the host see an out-of-list description instead of losing the entire
    # provider response to schema validation before we can salvage its fields.
    del schema["$defs"]["CaptionBoxDescription"]["properties"]["shape"]["enum"]

    def complete(extra: list[LlmPart]) -> LlmResult:
        request = LlmRequest(
            task=LlmTask.reference_vision,
            route=ROUTE,
            system=system,
            parts=[*parts, *extra],
            output_schema=schema,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            repair_invalid_output=False,
        )
        result = llm.complete(
            request,
            owner_id=ctx.owner_id,
            cancel=ctx.cancel,
            deadline=ctx.deadline,
            on_request=ctx.record_request,
        )
        ctx.record_usage(result.usage)
        return result

    with ctx.stage(Stage.ref_llm):
        kept: ReferenceValues | None = None
        try:
            first = complete([])
            kept = _without_caption_box(first)
            return kept.model_copy(update={"caption_box": _caption_box(first)})
        except AppError as error:
            if error.code != "llm_invalid_output":
                raise
            problem = error.detail.get("validation_rule", "json_object")
        except ValueError as error:
            problem = (
                error.errors(include_input=False, include_context=False)[:5]
                if isinstance(error, ValidationError)
                else str(error)
            )
        note = json.dumps({"validation_error": str(problem)[:1000]}, ensure_ascii=False)
        try:
            second = complete([LlmPart(kind="text", text=REPAIR_NOTE + note)])
            valid = kept if kept is not None else _without_caption_box(second)
            try:
                return valid.model_copy(update={"caption_box": _caption_box(second)})
            except ValueError:
                return valid
        except AppError as error:
            if error.code != "llm_invalid_output":
                raise
            if kept is not None:
                return kept
            raise
        except ValueError as final:
            raise AppError(
                "llm_invalid_output",
                detail={"task": LlmTask.reference_vision.value, "route": ROUTE},
            ) from final
