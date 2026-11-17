"""LLM port selected once from a profile and trusted injected configuration.

Integration example::

    client = LlmClient(settings, routing=settings.models,
                       options={"base_url": "https://endpoint.invalid/v1"})

This entry point does not change application defaults or read project content to
choose a provider. The composition root owns that wiring.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.llm.registry import create
from app.ports import (
    AppSettings,
    CancelToken,
    CredentialResolver,
    LlmRequest,
    LlmResult,
    RequestCallback,
)


class LlmClient:
    def __init__(self, settings: AppSettings, *, provider: str | None = None,
                 routing: Any = None, options: Mapping[str, Any] | None = None,
                 credentials: CredentialResolver | None = None) -> None:
        self._provider = create(
            settings,
            provider=provider,
            routing=routing,
            options=options,
            credentials=credentials,
        )

    def complete(
        self,
        req: LlmRequest,
        *,
        owner_id: str,
        cancel: CancelToken,
        deadline: float,
        on_request: RequestCallback | None = None,
    ) -> LlmResult:
        return self._provider.complete(
            req,
            owner_id=owner_id,
            cancel=cancel,
            deadline=deadline,
            on_request=on_request,
        )

    def auth_state(self, owner_id: str) -> str:
        return self._provider.auth_state(owner_id)
