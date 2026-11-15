"""Precheck: the promise, the answer, the factual claims and the assumptions."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.ports import AppError, JobContext, LlmPart, LlmPort, LlmTask, canonical_json
from app.schemas.api import Claim, PrecheckReport
from app.schemas.common import ContractModel, EntityId
from app.schemas.job import Stage, WaitingOn
from app.schemas.video import Video
from app.services.story.scene_data import ask_json

PRECHECK_MAX_TOKENS = 700


class ClaimChoice(ContractModel):
    scene_id: EntityId
    text: Annotated[str, Field(min_length=1, max_length=300)]
    material_id: EntityId | None = None


class PrecheckResponse(ContractModel):
    opening_promise: Annotated[str, Field(min_length=1, max_length=300)]
    ending_answer: Annotated[str, Field(min_length=1, max_length=300)]
    claims: Annotated[list[ClaimChoice], Field(max_length=20)]
    hypotheticals: Annotated[list[EntityId], Field(max_length=20)]


def run_precheck(video: Video, *, llm: LlmPort, ctx: JobContext) -> PrecheckReport:
    """Build the pre-generation report from the confirmed scenes and materials."""
    if not video.scene_order:
        raise AppError("scenes_not_confirmed", detail={"video_id": video.id})
    with ctx.stage(Stage.llm_precheck):
        ctx.progress(done=0, total=1, waiting_on=WaitingOn.llm)
        response = ask_json(
            route="precheck",
            task=LlmTask.precheck,
            schema_model=PrecheckResponse,
            parts=_precheck_parts(video),
            validate=lambda item: _precheck_problems(item, video),
            llm=llm,
            ctx=ctx,
            max_output_tokens=PRECHECK_MAX_TOKENS,
        )
        ctx.progress(done=1, total=1)
    return PrecheckReport(
        opening_promise=response.opening_promise,
        ending_answer=response.ending_answer,
        claims=[
            Claim(scene_id=item.scene_id, text=item.text, material_id=item.material_id)
            for item in response.claims
        ],
        hypotheticals=list(response.hypotheticals),
    )


def _precheck_parts(video: Video) -> list[LlmPart]:
    payload = {
        "language": video.settings.language.value,
        "register": video.settings.format.register_value.value,
        "story_structure": video.settings.format.story_structure,
        "scene_count": video.settings.format.scene_count,
        "scenes": [
            {
                "id": video.scenes[scene_id].id,
                "beat_label": video.scenes[scene_id].beat_label,
                "lines": [
                    {
                        "display_text": line.display_text,
                        "speech_text": line.speech_text,
                    }
                    for line in video.scenes[scene_id].lines
                ],
            }
            for scene_id in video.scene_order
        ],
        "materials": [{"id": item.id, "text": item.text} for item in video.material],
    }
    return [LlmPart(kind="text", text=canonical_json(payload).decode("utf-8"))]


def _precheck_problems(response: PrecheckResponse, video: Video) -> list[str]:
    problems: list[str] = []
    scene_ids = set(video.scene_order)
    material_ids = {item.id for item in video.material}
    for item in response.claims:
        if item.scene_id not in scene_ids:
            problems.append(f"claim scene_id {item.scene_id} is not a scene of this video")
        if item.material_id is not None and item.material_id not in material_ids:
            problems.append(f"claim material_id {item.material_id} is not a material of this video")
    if len(response.hypotheticals) != len(set(response.hypotheticals)):
        problems.append("hypotheticals must not repeat a scene id")
    for scene_id in response.hypotheticals:
        if scene_id not in scene_ids:
            problems.append(f"hypothetical scene_id {scene_id} is not a scene of this video")
    return problems


__all__ = ["run_precheck"]
