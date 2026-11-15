"""Composition entry point for explicit profiles and injected provider options.

The caller supplies the already-resolved models/routes from models.yaml. For an
OpenAI-compatible endpoint, supply base_url and optional credentials/key_required
in options and set its alias model IDs in routing.models. No endpoint discovery,
profile mutation or model fallback occurs here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.ports import AppSettings, LlmPort

DEFAULT_PROVIDERS = {
    "fixture": "fixture", "dev": "openai_compat", "release": "anthropic_api",
}


def create(settings: AppSettings, *, provider: str | None = None,
           routing: Any = None, options: Mapping[str, Any] | None = None) -> LlmPort:
    try:
        selected = provider or DEFAULT_PROVIDERS[settings.profile]
    except KeyError:
        raise ValueError("unknown LLM profile") from None
    if selected == "claude_cli" and settings.profile != "dev":
        raise ValueError("claude_cli is only available in the dev profile")
    if selected == "fixture":
        from app.llm.providers.fixture.adapter import FixtureLlm
        return FixtureLlm(**dict(options or {}))
    if selected == "anthropic_api":
        from app.llm.providers.anthropic_api.adapter import AnthropicApiLlm
        return AnthropicApiLlm(settings, routing=routing, **dict(options or {}))
    if selected == "openai_compat":
        from app.llm.providers.openai_compat.adapter import OpenAiCompatLlm
        return OpenAiCompatLlm(settings, routing=routing, **dict(options or {}))
    if selected == "claude_cli":
        from app.llm.providers.claude_cli.adapter import ClaudeCliLlm
        return ClaudeCliLlm(settings, routing=routing, **dict(options or {}))
    raise ValueError("unknown LLM provider")
