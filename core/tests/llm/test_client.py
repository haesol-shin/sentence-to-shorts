from __future__ import annotations

import io
import json
import time
from types import SimpleNamespace

import pytest

from app.llm.client import LlmClient
from app.llm.credentials import Credentials
from app.ports import AppError


class MemoryBackend:
    value = None

    def get_password(self, service, account):
        return self.value

    def set_password(self, service, account, value):
        self.value = value

    def delete_password(self, service, account):
        self.value = None


def test_10_4_keyring_replacement_and_deletion():
    backend = MemoryBackend()
    source = Credentials("synthetic.invalid", "api", backend_factory=lambda: backend)
    source.set("first-secret")
    assert source.read() == "first-secret"
    assert source.persistent is True
    source.set("replacement-secret")
    assert source.read() == "replacement-secret"
    source.delete()
    assert source.read() is None
    assert "secret" not in repr(source)


def test_10_4_missing_keyring_preserves_key_only_in_memory():
    def unavailable():
        raise RuntimeError("private-backend-error")

    source = Credentials("synthetic.invalid", "api", backend_factory=unavailable)
    source.set("synthetic-secret")
    assert source.read() == "synthetic-secret"
    assert source.persistent is False
    other = Credentials("synthetic.invalid", "api", backend_factory=unavailable)
    assert other.read() is None
    source.delete()
    assert source.read() is None


def test_10_2_dev_client_uses_injected_endpoint_alias(settings, request_data, cancel):
    class Http:
        payload = None

        def open(self, request, *, timeout):
            self.payload = json.loads(request.data)
            assert request.full_url == "https://endpoint.invalid/v1/chat/completions"
            return io.BytesIO(b'{"model":"selected-model","choices":'
                              b'[{"message":{"content":"{\\"answer\\":\\"ok\\"}"}}]}')

    transport = Http()
    source = Credentials("synthetic.invalid", "api", backend_factory=lambda: None)
    routing = SimpleNamespace(models={"haiku": {"openai_compat": "injected-model"}},
                              routes=settings.models.routes)
    client = LlmClient(settings, routing=routing, options={
        "base_url": "https://endpoint.invalid/v1", "opener": transport, "credentials": source,
    })
    result = client.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert result.parsed == {"answer": "ok"}
    assert result.usage.provider == "openai_compat"
    assert transport.payload["model"] == "injected-model"
    assert settings.models.models["haiku"]["openai_compat"] == "small-synthetic"


def test_10_2_release_client_requires_os_api_key(settings, request_data, cancel, monkeypatch):
    settings.profile = "release"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unconfigured-secret")
    source = Credentials("synthetic.invalid", "api", backend_factory=lambda: None)
    client = LlmClient(settings, options={"credentials": source})
    assert client.auth_state() == "missing"
    with pytest.raises(AppError, match="llm_auth"):
        client.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)


def test_10_2_cli_cannot_be_selected_in_release(settings):
    settings.profile = "release"
    with pytest.raises(ValueError, match="only available in the dev"):
        LlmClient(settings, provider="claude_cli")


def test_10_2_unknown_provider_does_not_fallback(settings):
    with pytest.raises(ValueError, match="unknown LLM provider"):
        LlmClient(settings, provider="missing")


def test_10_4_failed_os_delete_does_not_reactivate_old_key():
    class UnavailableDelete(MemoryBackend):
        def delete_password(self, service, account):
            raise RuntimeError("store unavailable")

    backend = UnavailableDelete()
    source = Credentials("synthetic.invalid", "api", backend_factory=lambda: backend)
    source.set("synthetic-secret")
    source.delete()
    assert source.read() is None
    assert source.persistent is False
