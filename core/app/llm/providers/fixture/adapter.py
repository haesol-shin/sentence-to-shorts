"""Recorded-response LLM provider for the fixture profile and tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.llm.common import validate_output
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
    payload: dict[str, object] = {"kind": part.kind}
    if part.text is not None:
        payload["text"] = part.text
    if part.png is not None:
        payload["png_sha256"] = hashlib.sha256(part.png).hexdigest()
    return payload


def _record_error(task: LlmTask, reason: str) -> AppError:
    return AppError("llm_invalid_output", detail={"task": task.value, "record": reason})


def _request_record(record: Any, task: LlmTask) -> dict[str, Any]:
    """Normalize a stored request so it can be checked against the digest again."""
    if not isinstance(record, dict):
        raise _record_error(task, "request")
    recorded_task = record.get("task")
    route = record.get("route")
    system = record.get("system")
    parts = record.get("parts")
    output_schema = record.get("output_schema")
    max_output_tokens = record.get("max_output_tokens")
    if recorded_task != task.value:
        raise _record_error(task, "request")
    if not isinstance(route, str) or not isinstance(system, str):
        raise _record_error(task, "request")
    if not isinstance(parts, list):
        raise _record_error(task, "request")
    if output_schema is not None and not isinstance(output_schema, dict):
        raise _record_error(task, "request")
    if (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens < 0
    ):
        raise _record_error(task, "request")
    normalized_parts: list[dict[str, object]] = []
    for part in parts:
        if not isinstance(part, dict):
            raise _record_error(task, "request")
        kind = part.get("kind")
        if not isinstance(kind, str):
            raise _record_error(task, "request")
        payload: dict[str, object] = {"kind": kind}
        text = part.get("text")
        if text is not None:
            if not isinstance(text, str):
                raise _record_error(task, "request")
            payload["text"] = text
        png_sha256 = part.get("png_sha256")
        if png_sha256 is not None:
            if not isinstance(png_sha256, str):
                raise _record_error(task, "request")
            payload["png_sha256"] = png_sha256
        normalized_parts.append(payload)
    return {
        "task": recorded_task,
        "route": route,
        "system": system,
        "parts": normalized_parts,
        "output_schema": output_schema,
        "max_output_tokens": max_output_tokens,
    }


class FixtureLlm(LlmPort):
    """Returns the response recorded for the request digest.

    A missing, malformed or mismatched record fails with llm_invalid_output; it
    never invents text. The stored request is checked against the same digest
    that names the file so a response cannot be returned for another request.
    When the request has an output schema the recorded text is validated by the
    common output helper, and a recorded parsed value must agree with it.
    """

    provider = "fixture"

    def __init__(self, root: Path = FIXTURE_ROOT) -> None:
        self.root = root

    def _load_record(self, req: LlmRequest) -> dict[str, Any]:
        digest = request_digest(req)
        path = self.root / req.task.value / f"{digest}.json"
        if not path.is_file():
            raise AppError(
                "llm_invalid_output", detail={"task": req.task.value, "digest": digest}
            )
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise _record_error(req.task, "unreadable") from None
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            raise _record_error(req.task, "malformed") from None
        if not isinstance(payload, dict):
            raise _record_error(req.task, "malformed")
        if payload.get("task") != req.task.value:
            raise _record_error(req.task, "task")
        normalized = _request_record(payload.get("request"), req.task)
        try:
            recorded_digest = canonical_digest(normalized)
        except (TypeError, ValueError):
            raise _record_error(req.task, "request") from None
        if recorded_digest != digest:
            raise _record_error(req.task, "request")
        if not isinstance(payload.get("text"), str):
            raise _record_error(req.task, "text")
        return payload

    def complete(
        self, req: LlmRequest, *, cancel: CancelToken, deadline: float
    ) -> LlmResult:
        # Recorded playback has no provider call. Keep the original fixture
        # semantics: cancellation is observed, but an absolute wall-clock
        # deadline is not consumed by a local file read.
        cancel.raise_if_set()
        payload = self._load_record(req)
        cancel.raise_if_set()
        text = payload["text"]
        recorded_parsed = payload.get("parsed")
        if req.output_schema is None:
            if recorded_parsed is not None and not isinstance(recorded_parsed, dict):
                raise _record_error(req.task, "parsed")
            parsed = recorded_parsed
        else:
            parsed = validate_output(text, req.output_schema)
            if recorded_parsed is not None and recorded_parsed != parsed:
                raise _record_error(req.task, "parsed")
        cancel.raise_if_set()
        return LlmResult(
            text=text,
            parsed=parsed,
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
