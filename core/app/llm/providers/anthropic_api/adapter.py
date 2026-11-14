"""Anthropic API provider. The official SDK lands with the LLM adapter task."""

from __future__ import annotations

from app.ports import AppSettings, CancelToken, LlmRequest, LlmResult


class AnthropicApiLlm:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def complete(
        self, req: LlmRequest, *, cancel: CancelToken, deadline: float
    ) -> LlmResult:
        raise NotImplementedError

    def auth_state(self) -> str:
        raise NotImplementedError


def create(settings: AppSettings) -> AnthropicApiLlm:
    raise NotImplementedError("llm/providers/anthropic_api")
