"""Synthetic configuration and deterministic cancellation for adapter tests."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from app.ports import Cancelled, LlmPart, LlmRequest, LlmTask

SCHEMA = {
    "type": "object", "properties": {"answer": {"type": "string"}},
    "required": ["answer"], "additionalProperties": False,
}


class Cancel:
    def __init__(self) -> None:
        self.event = threading.Event()

    def is_set(self) -> bool:
        return self.event.is_set()

    def raise_if_set(self) -> None:
        if self.is_set():
            raise Cancelled()

    def wait(self, seconds: float) -> bool:
        return self.event.wait(seconds)


@pytest.fixture
def settings(tmp_path):
    aliases = {
        "haiku": {"openai_compat": "small-synthetic", "anthropic_api": "claude-haiku-5-5",
                  "claude_cli": "haiku"},
        "sonnet": {"openai_compat": "large-synthetic", "anthropic_api": "claude-sonnet-5-5",
                   "claude_cli": "sonnet"},
    }
    return SimpleNamespace(
        profile="dev", brand=SimpleNamespace(app_id="synthetic.invalid"),
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data",
        models=SimpleNamespace(models=aliases, routes={
            "draft": SimpleNamespace(model="haiku", effort="low", timeout_s=30, retries=2),
            "script.default": SimpleNamespace(model="sonnet", effort="medium",
                                               timeout_s=40, retries=2),
            "reference_vision": SimpleNamespace(model="sonnet", effort="medium",
                                                 timeout_s=40, retries=2),
        }),
    )


@pytest.fixture
def request_data():
    return LlmRequest(LlmTask.draft, "draft", "Return the requested object.",
                      [LlmPart("text", text="합성 주제 <문장>")], SCHEMA, 128)


@pytest.fixture
def cancel():
    return Cancel()
