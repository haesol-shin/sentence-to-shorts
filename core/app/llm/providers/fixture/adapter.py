"""Recorded-response LLM provider for the fixture profile and tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.ports import (
    AppError,
    AppSettings,
    CancelToken,
    LlmPart,
    LlmPort,
    LlmRequest,
    LlmResult,
    LlmTask,
    canonical_digest,
)
from app.schemas.job import Stage, Usage

FIXTURE_ROOT = Path(__file__).resolve().parents[5] / "fixtures" / "llm"

STAGE_BY_TASK = {
    LlmTask.draft: Stage.llm_draft,
    LlmTask.script: Stage.llm_script,
    LlmTask.split: Stage.llm_split,
    LlmTask.scene_data: Stage.llm_scene_data,
    LlmTask.chat: Stage.llm_chat,
    LlmTask.scene_rewrite: Stage.llm_chat,
    LlmTask.precheck: Stage.llm_precheck,
    LlmTask.reference_vision: Stage.ref_llm,
    LlmTask.style_code: Stage.code_llm,
    LlmTask.template_code: Stage.code_llm,
    LlmTask.bgm_code: Stage.code_llm,
}


def request_digest(req: LlmRequest) -> str:
    """Digest of the recorded request, used as the fixture file name."""
    return canonical_digest(
        {
            "task": req.task.value,
            "route": req.route,
            "system": req.system,
            "parts": [_part_payload(part) for part in req.parts],
            "output_schema": req.output_schema,
            "max_output_tokens": req.max_output_tokens,
        }
    )


def _part_payload(part: LlmPart) -> dict[str, object]:
    import hashlib

    payload: dict[str, object] = {"kind": part.kind}
    if part.text is not None:
        payload["text"] = part.text
    if part.png is not None:
        payload["png_sha256"] = hashlib.sha256(part.png).hexdigest()
    return payload


class FixtureLlm(LlmPort):
    """Returns the response recorded for the request digest.

    A missing record fails with llm_invalid_output; it never invents text.
    Recorded parsed values are reviewed fixture contracts, so an adapter-side
    JSON Schema check is not needed for this profile.
    """

    def __init__(self, root: Path = FIXTURE_ROOT) -> None:
        self.root = root

    def complete(
        self, req: LlmRequest, *, cancel: CancelToken, deadline: float
    ) -> LlmResult:
        cancel.raise_if_set()
        digest = request_digest(req)
        path = self.root / req.task.value / f"{digest}.json"
        if not path.is_file():
            raise AppError(
                "llm_invalid_output", detail={"task": req.task.value, "digest": digest}
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        cancel.raise_if_set()
        return LlmResult(
            text=payload["text"],
            parsed=payload.get("parsed"),
            usage=Usage(
                stage=STAGE_BY_TASK[req.task],
                provider="fixture",
                model="fixture",
                effort=None,
                input_tokens=None,
                output_tokens=None,
                cache_read_tokens=None,
                cost_usd=None,
                wall_ms=0,
                retries=0,
            ),
        )

    def auth_state(self) -> str:
        return "ok"


def create(settings: AppSettings) -> FixtureLlm:
    return FixtureLlm()
