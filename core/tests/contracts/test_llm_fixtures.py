"""Recorded LLM responses play back through the fixture adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.llm.providers.fixture.adapter import FixtureLlm, request_digest
from app.ports import LlmPart, LlmRequest, LlmTask

LLM_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "llm"
STORY_TASKS = ("draft", "script", "split", "scene_data", "chat", "precheck")


class _NotCancelled:
    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


def _recordings() -> list[Path]:
    return sorted(LLM_ROOT.glob("*/*.json"))


def _request(payload: dict) -> LlmRequest:
    request = payload["request"]
    return LlmRequest(
        task=LlmTask(request["task"]),
        route=request["route"],
        system=request["system"],
        parts=[
            LlmPart(kind=part["kind"], text=part.get("text"))
            for part in request["parts"]
        ],
        output_schema=request["output_schema"],
        max_output_tokens=request["max_output_tokens"],
    )


@pytest.mark.parametrize("path", _recordings(), ids=lambda path: path.stem[:12])
def test_recorded_response_plays_back(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    request = _request(payload)
    assert path.stem == request_digest(request)

    result = FixtureLlm(LLM_ROOT).complete(
        request, cancel=_NotCancelled(), deadline=1.0
    )
    assert result.text == payload["text"]
    assert result.parsed == payload["parsed"]
    if request.task is LlmTask.split:
        assert isinstance(result.parsed, dict)
        assert isinstance(result.parsed["beats"], list)


def test_route_takes_part_in_the_request_digest() -> None:
    payload = json.loads(_recordings()[0].read_text(encoding="utf-8"))
    request = _request(payload)
    other = LlmRequest(
        task=request.task,
        route="other_route",
        system=request.system,
        parts=request.parts,
        output_schema=request.output_schema,
        max_output_tokens=request.max_output_tokens,
    )
    assert request_digest(request) != request_digest(other)


def test_each_story_task_has_korean_and_english_recordings() -> None:
    for task in STORY_TASKS:
        parts = [
            json.loads(path.read_text(encoding="utf-8"))["request"]["parts"][0]["text"]
            for path in sorted((LLM_ROOT / task).glob("*.json"))
        ]
        assert len(parts) >= 2, task
        assert any(text.isascii() for text in parts), task
        assert any(not text.isascii() for text in parts), task
