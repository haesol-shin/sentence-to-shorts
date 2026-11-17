"""Keyring vault, credential store and client wiring for owner-scoped keys."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm.client import LlmClient
from app.llm.credentials import KeyringVault
from app.ports import AppError
from app.storage.credentials import SqliteCredentialStore
from app.storage.sqlite import Database
from tests.llm.conftest import CREDENTIAL_ID, OWNER, FakeResolver


class MemoryBackend:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_password(self, service, account):
        return self.values.get(account)

    def set_password(self, service, account, value):
        self.values[account] = value

    def delete_password(self, service, account):
        self.values.pop(account, None)


def test_10_4_keyring_replacement_and_deletion():
    backend = MemoryBackend()
    vault = KeyringVault("synthetic.invalid", backend_factory=lambda: backend)
    vault.put(OWNER, "api", CREDENTIAL_ID, "first-secret")
    assert vault.get(OWNER, "api", CREDENTIAL_ID) == "first-secret"
    assert vault.persistent is True
    assert list(backend.values) == [f"{OWNER}:api"]

    vault.put(OWNER, "api", CREDENTIAL_ID, "replacement-secret")
    assert vault.get(OWNER, "api", CREDENTIAL_ID) == "replacement-secret"
    vault.delete(OWNER, "api", CREDENTIAL_ID)
    assert vault.get(OWNER, "api", CREDENTIAL_ID) is None
    assert "secret" not in repr(vault)


def test_10_4_missing_keyring_preserves_key_only_in_memory():
    def unavailable():
        raise RuntimeError("private-backend-error")

    vault = KeyringVault("synthetic.invalid", backend_factory=unavailable)
    vault.put(OWNER, "api", CREDENTIAL_ID, "synthetic-secret")
    assert vault.get(OWNER, "api", CREDENTIAL_ID) == "synthetic-secret"
    assert vault.persistent is False
    other = KeyringVault("synthetic.invalid", backend_factory=unavailable)
    assert other.get(OWNER, "api", CREDENTIAL_ID) is None
    vault.delete(OWNER, "api", CREDENTIAL_ID)
    assert vault.get(OWNER, "api", CREDENTIAL_ID) is None


def test_keyring_legacy_account_moves_once(tmp_path: Path):
    backend = MemoryBackend()
    backend.values["anthropic_api"] = "legacy-secret"
    vault = KeyringVault("synthetic.invalid", backend_factory=lambda: backend)
    database = Database.open(tmp_path / "state.db")
    try:
        store = SqliteCredentialStore(database, vault)
        assert vault.move_legacy(store, OWNER, "anthropic_api") is True
        assert backend.values == {f"{OWNER}:anthropic_api": "legacy-secret"}
        assert store.resolve(OWNER, "anthropic_api") is not None
        assert store.resolve(OWNER, "anthropic_api").secret == "legacy-secret"
        assert vault.move_legacy(store, OWNER, "anthropic_api") is False
    finally:
        database.close()


def test_keyring_legacy_move_keeps_old_item_when_the_store_write_fails(tmp_path: Path):
    backend = MemoryBackend()
    backend.values["anthropic_api"] = "legacy-secret"
    vault = KeyringVault("synthetic.invalid", backend_factory=lambda: backend)
    database = Database.open(tmp_path / "state.db")
    try:
        store = SqliteCredentialStore(database, vault)

        def fail(*args, **kwargs):
            raise RuntimeError("store unavailable")

        store.put = fail  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="store unavailable"):
            vault.move_legacy(store, OWNER, "anthropic_api")
        assert backend.values["anthropic_api"] == "legacy-secret"
    finally:
        database.close()


def test_10_2_dev_client_uses_injected_endpoint_alias(settings, request_data, cancel):
    class Http:
        payload = None

        def open(self, request, *, timeout):
            self.payload = json.loads(request.data)
            assert request.full_url == "https://endpoint.invalid/v1/chat/completions"
            return io.BytesIO(b'{"model":"selected-model","choices":'
                              b'[{"message":{"content":"{\\"answer\\":\\"ok\\"}"}}]}')

    transport = Http()
    source = FakeResolver(None)
    routing = SimpleNamespace(models={"haiku": {"openai_compat": "injected-model"}},
                              routes=settings.models.routes)
    client = LlmClient(
        settings,
        routing=routing,
        credentials=source,
        options={"base_url": "https://endpoint.invalid/v1", "opener": transport},
    )
    result = client.complete(
        request_data, owner_id=OWNER, cancel=cancel, deadline=time.monotonic() + 10
    )
    assert result.parsed == {"answer": "ok"}
    assert result.usage.provider == "openai_compat"
    assert transport.payload["model"] == "injected-model"
    assert settings.models.models["haiku"]["openai_compat"] == "small-synthetic"


def test_10_2_release_client_requires_os_api_key(settings, request_data, cancel, monkeypatch):
    settings.profile = "release"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unconfigured-secret")
    client = LlmClient(settings, credentials=FakeResolver(None))
    assert client.auth_state(OWNER) == "missing"
    with pytest.raises(AppError, match="llm_auth"):
        client.complete(
            request_data, owner_id=OWNER, cancel=cancel, deadline=time.monotonic() + 10
        )


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
    vault = KeyringVault("synthetic.invalid", backend_factory=lambda: backend)
    vault.put(OWNER, "api", CREDENTIAL_ID, "synthetic-secret")
    vault.delete(OWNER, "api", CREDENTIAL_ID)
    assert vault.get(OWNER, "api", CREDENTIAL_ID) is None
    assert vault.persistent is False
