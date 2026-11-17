"""The credentials table: one key slot per owner and provider (CONTRACTS 10.4).

Metadata lives here; the secret lives in an injected `SecretVault` (the OS
keyring in personal mode). `put` issues a new credential id, so a replaced key
is told apart from its predecessor in usage records. A row whose secret the
vault no longer holds counts as missing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.ports import AppError, ResolvedCredential, SecretVault
from app.schemas.credential import CredentialInfo
from app.storage.projects import new_typeid, utc_text
from app.storage.sqlite import Database

_COLUMNS = "id, provider, label, last4, created_at, last_used_at"


def _row_info(row: tuple[Any, ...]) -> CredentialInfo:
    return CredentialInfo(
        id=row[0],
        provider=row[1],
        label=row[2],
        last4=row[3],
        created_at=datetime.fromisoformat(row[4]),
        last_used_at=None if row[5] is None else datetime.fromisoformat(row[5]),
    )


class SqliteCredentialStore:
    """CredentialStore and CredentialResolver over `credentials` and a vault."""

    def __init__(self, db: Database, vault: SecretVault) -> None:
        self._db = db
        self._vault = vault

    def put(
        self, owner_id: str, provider: str, secret: str, label: str | None
    ) -> CredentialInfo:
        if not secret:
            raise ValueError("credential secret is empty")
        credential_id = new_typeid("k")
        now = datetime.now(UTC)
        previous = self._secret(owner_id, provider)
        self._vault.put(owner_id, provider, credential_id, secret)
        try:
            with self._db.write() as conn:
                conn.execute(
                    "INSERT INTO credentials "
                    "(id, owner_id, provider, label, last4, created_at, last_used_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, NULL) "
                    "ON CONFLICT (owner_id, provider) DO UPDATE SET "
                    "id = excluded.id, label = excluded.label, last4 = excluded.last4, "
                    "created_at = excluded.created_at, last_used_at = NULL, "
                    "key_id = NULL, nonce = NULL, ciphertext = NULL",
                    (
                        credential_id,
                        owner_id,
                        provider,
                        label,
                        secret[-4:],
                        utc_text(now),
                    ),
                )
        except BaseException:
            if previous is None:
                self._vault.delete(owner_id, provider, credential_id)
            else:
                self._vault.put(owner_id, provider, credential_id, previous)
            raise
        return CredentialInfo(
            id=credential_id,
            provider=provider,
            label=label,
            last4=secret[-4:],
            created_at=now,
            last_used_at=None,
        )

    def list(self, owner_id: str) -> list[CredentialInfo]:
        with self._db.read() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM credentials WHERE owner_id = ? "
                "ORDER BY created_at, id",
                (owner_id,),
            ).fetchall()
        return [_row_info(row) for row in rows]

    def delete(self, owner_id: str, provider: str) -> None:
        with self._db.write() as conn:
            row = conn.execute(
                "SELECT id FROM credentials WHERE owner_id = ? AND provider = ?",
                (owner_id, provider),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                "DELETE FROM credentials WHERE owner_id = ? AND provider = ?",
                (owner_id, provider),
            )
        self._vault.delete(owner_id, provider, row[0])

    def resolve(self, owner_id: str, provider: str) -> ResolvedCredential | None:
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT id FROM credentials WHERE owner_id = ? AND provider = ?",
                (owner_id, provider),
            ).fetchone()
        if row is None:
            return None
        secret = self._vault.get(owner_id, provider, row[0])
        if secret is None:
            return None
        with self._db.write() as conn:
            conn.execute(
                "UPDATE credentials SET last_used_at = ? "
                "WHERE owner_id = ? AND provider = ?",
                (utc_text(datetime.now(UTC)), owner_id, provider),
            )
        return ResolvedCredential(credential_id=row[0], secret=secret)

    def credential_id(self, owner_id: str, provider: str) -> str | None:
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT id FROM credentials WHERE owner_id = ? AND provider = ?",
                (owner_id, provider),
            ).fetchone()
        if row is None:
            return None
        return row[0] if self._vault.get(owner_id, provider, row[0]) is not None else None

    def _secret(self, owner_id: str, provider: str) -> str | None:
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT id FROM credentials WHERE owner_id = ? AND provider = ?",
                (owner_id, provider),
            ).fetchone()
        if row is None:
            return None
        return self._vault.get(owner_id, provider, row[0])

    def require(self, owner_id: str, provider: str) -> CredentialInfo:
        for info in self.list(owner_id):
            if info.provider == provider:
                return info
        raise AppError("not_found")


__all__ = ["SqliteCredentialStore"]
