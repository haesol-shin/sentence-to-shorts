"""The credentials table and its vault: one slot per owner and provider."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.storage.credentials import SqliteCredentialStore
from app.storage.sqlite import Database

OWNER = "owner"
OTHER_OWNER = "u_0hzb7bexv28termtt2ypc6trzt"


class Vault:
    """In-memory SecretVault keyed by (owner, provider)."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.deleted: list[tuple[str, str]] = []

    def get(self, owner_id: str, provider: str, credential_id: str) -> str | None:
        return self.values.get((owner_id, provider))

    def put(self, owner_id: str, provider: str, credential_id: str, secret: str) -> None:
        self.values[(owner_id, provider)] = secret

    def delete(self, owner_id: str, provider: str, credential_id: str) -> None:
        self.values.pop((owner_id, provider), None)
        self.deleted.append((owner_id, provider))


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database.open(tmp_path / "state.db")
    yield database
    database.close()


@pytest.fixture
def vault() -> Vault:
    return Vault()


@pytest.fixture
def store(db: Database, vault: Vault) -> SqliteCredentialStore:
    return SqliteCredentialStore(db, vault)


def test_credential_put_resolve_and_delete(store, vault: Vault) -> None:
    info = store.put(OWNER, "anthropic_api", "synthetic-secret-value", "personal")
    assert info.id.startswith("k_")
    assert info.last4 == "alue"
    assert info.label == "personal"
    assert store.credential_id(OWNER, "anthropic_api") == info.id

    resolved = store.resolve(OWNER, "anthropic_api")
    assert resolved is not None
    assert resolved.credential_id == info.id
    assert resolved.secret == "synthetic-secret-value"

    store.delete(OWNER, "anthropic_api")
    assert store.credential_id(OWNER, "anthropic_api") is None
    assert (OWNER, "anthropic_api") not in vault.values


def test_credential_replacement_issues_a_new_id(store, vault: Vault) -> None:
    first = store.put(OWNER, "openai_compat", "first-secret-value", None)
    second = store.put(OWNER, "openai_compat", "second-secret-value", None)
    assert first.id != second.id
    assert store.credential_id(OWNER, "openai_compat") == second.id
    assert store.resolve(OWNER, "openai_compat").secret == "second-secret-value"
    assert len(store.list(OWNER)) == 1


def test_credential_is_scoped_by_owner(store) -> None:
    mine = store.put(OWNER, "anthropic_api", "owner-secret-value", None)
    theirs = store.put(OTHER_OWNER, "anthropic_api", "other-secret-value", None)
    assert mine.id != theirs.id
    assert store.resolve(OTHER_OWNER, "anthropic_api").secret == "other-secret-value"
    assert store.resolve(OWNER, "anthropic_api").secret == "owner-secret-value"
    assert store.credential_id("u_nobody", "anthropic_api") is None


def test_credential_without_a_vault_secret_counts_as_missing(store, vault: Vault) -> None:
    info = store.put(OWNER, "anthropic_api", "lost-secret-value", None)
    del vault.values[(OWNER, "anthropic_api")]
    assert store.credential_id(OWNER, "anthropic_api") is None
    assert store.resolve(OWNER, "anthropic_api") is None
    assert store.list(OWNER)[0].id == info.id


def test_credential_delete_removes_the_row_and_the_vault_secret(store, vault: Vault) -> None:
    store.put(OWNER, "anthropic_api", "delete-secret-value", None)
    store.delete(OWNER, "anthropic_api")
    assert store.list(OWNER) == []
    assert vault.deleted == [(OWNER, "anthropic_api")]
    store.delete(OWNER, "anthropic_api")
    assert vault.deleted == [(OWNER, "anthropic_api")]
