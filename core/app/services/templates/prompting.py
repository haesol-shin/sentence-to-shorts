"""Prompt files and model calls for the generated code routes.

Prompt files live next to the routes they serve: ``prompts/<route>/prompt.md``
with ``style-fixtures.jsonl`` review inputs beside them. The loader strips the
front matter, checks that the data variables match the declaration and returns
only the trusted body as the system prompt. Request text, reference hints,
earlier code and failure text travel as one data part, never inside system.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from app.ports import AppError, JobContext, LlmPart, LlmPort, LlmRequest, LlmResult, LlmTask
from app.schemas.job import Stage, Usage

PROMPT_ROOT = Path(__file__).resolve().parent / "prompts"
REPAIR_NOTE = "\n\n# Repair\n\nReturn corrected JSON that validates against the schema.\n"
FAILURE_TEXT_LIMIT = 4000

ModelT = TypeVar("ModelT", bound=BaseModel)


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


def load_prompt(route: str, data: Mapping[str, Any]) -> str:
    """Return the trusted system body; reject undeclared or missing data variables."""
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
    if not isinstance(declared, list) or set(declared) != set(data):
        raise AppError("internal", detail={"prompt": route, "problem": "variables"})
    if not body:
        raise AppError("internal", detail={"prompt": route, "problem": "body"})
    return body + "\n"


def _data_text(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)


def _parsed(result: LlmResult, model: type[ModelT]) -> ModelT:
    if result.parsed is None:
        raise ValueError("output is not a JSON object")
    return model.model_validate(result.parsed)


@dataclass(frozen=True)
class CodeAnswer(Generic[ModelT]):
    """A validated model answer and the usage of the call that produced it."""

    value: ModelT
    usage: Usage


def complete_json(
    llm: LlmPort,
    *,
    task: LlmTask,
    route: str,
    model: type[ModelT],
    data: Mapping[str, Any],
    max_output_tokens: int,
    ctx: JobContext,
) -> CodeAnswer[ModelT]:
    """Call the model once, repair an invalid output once, then fail with llm_invalid_output."""
    system = load_prompt(route, data)
    parts = [LlmPart(kind="text", text=_data_text(data))]
    schema = model.model_json_schema()
    request = LlmRequest(
        task=task,
        route=route,
        system=system,
        parts=parts,
        output_schema=schema,
        max_output_tokens=max_output_tokens,
    )
    with ctx.stage(Stage.code_llm):
        first = llm.complete(
            request,
            owner_id=ctx.owner_id,
            cancel=ctx.cancel,
            deadline=ctx.deadline,
            on_request=ctx.record_request,
        )
        ctx.record_usage(first.usage)
        try:
            return CodeAnswer(_parsed(first, model), first.usage)
        except ValueError as error:
            problem = error.errors()[:5] if isinstance(error, ValidationError) else str(error)
            note = json.dumps({"validation_error": str(problem)[:1000]}, ensure_ascii=False)
        second = llm.complete(
            LlmRequest(
                task=task,
                route=route,
                system=system + REPAIR_NOTE,
                parts=[*parts, LlmPart(kind="text", text=note)],
                output_schema=schema,
                max_output_tokens=max_output_tokens,
            ),
            owner_id=ctx.owner_id,
            cancel=ctx.cancel,
            deadline=ctx.deadline,
            on_request=ctx.record_request,
        )
        ctx.record_usage(second.usage)
        try:
            return CodeAnswer(_parsed(second, model), second.usage)
        except ValueError as final:
            raise AppError(
                "llm_invalid_output", detail={"task": task.value, "route": route}
            ) from final


def failure_text(error: AppError) -> dict[str, str]:
    """The failure handed back to the model for a repair; never written to logs."""
    message = error.detail.get("message") or error.detail.get("reason") or ""
    return {"code": error.code, "message": str(message)[-FAILURE_TEXT_LIMIT:]}


__all__ = ["PROMPT_ROOT", "CodeAnswer", "complete_json", "failure_text", "load_prompt"]
