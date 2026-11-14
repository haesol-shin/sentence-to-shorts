"""Official Claude CLI provider. Implemented by the LLM adapter task."""

from __future__ import annotations

from app.ports import AppSettings, CancelToken, LlmRequest, LlmResult


class ClaudeCliLlm:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def complete(
        self, req: LlmRequest, *, cancel: CancelToken, deadline: float
    ) -> LlmResult:
        raise NotImplementedError

    def auth_state(self) -> str:
        raise NotImplementedError


def create(settings: AppSettings) -> ClaudeCliLlm:
    raise NotImplementedError("llm/providers/claude_cli")
