"""Synthetic configuration and deterministic cancellation for adapter tests."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from app.ports import Cancelled, LlmPart, LlmRequest, LlmTask, ResolvedCredential

SCHEMA = {
    "type": "object", "properties": {"answer": {"type": "string"}},
    "required": ["answer"], "additionalProperties": False,
}

OWNER = "owner"
CREDENTIAL_ID = "k_01jdq7c3v8m4n5p6q7r8s9t0vw"


class FakeResolver:
    """One credential slot per (owner, provider); enough for adapter tests."""

    def __init__(self, secret: str | None = None, credential_id: str = CREDENTIAL_ID) -> None:
        self.keys: dict[tuple[str, str], ResolvedCredential] = {}
        if secret is not None:
            self.keys[(OWNER, "any")] = ResolvedCredential(credential_id, secret)
        self.default_id = credential_id

    def set(
        self,
        secret: str | None,
        owner_id: str = OWNER,
        credential_id: str | None = None,
    ) -> None:
        self.keys = {
            key: value for key, value in self.keys.items() if key[0] != owner_id
        }
        if secret is not None:
            self.keys[(owner_id, "any")] = ResolvedCredential(
                credential_id or self.default_id, secret
            )

    def resolve(self, owner_id: str, provider: str) -> ResolvedCredential | None:
        found = self.keys.get((owner_id, provider))
        if found is not None:
            return found
        return self.keys.get((owner_id, "any"))

    def credential_id(self, owner_id: str, provider: str) -> str | None:
        resolved = self.resolve(owner_id, provider)
        return None if resolved is None else resolved.credential_id


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
