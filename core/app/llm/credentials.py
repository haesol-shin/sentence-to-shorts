"""Keyring vault for personal-mode keys with an in-memory-only fallback.

Only Windows Credential Manager and Linux Secret Service are selected. A missing
OS store never enables a plaintext backend. Keys are never written to app state.
The account name is `<owner_id>:<provider>`; an item stored under the old account
name `<provider>` is moved once at startup through the credential store.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any


def _account(owner_id: str, provider: str) -> str:
    return f"{owner_id}:{provider}"


class KeyringVault:
    """SecretVault over the OS keyring, with a process-memory fallback."""

    def __init__(
        self,
        service: str,
        *,
        backend_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.service = service
        self._memory: dict[str, str] = {}
        self._deleted: set[str] = set()
        self._factory = backend_factory or _os_backend
        self.persistent = False

    def _backend(self) -> Any:
        try:
            backend = self._factory()
        except Exception:
            backend = None
        self.persistent = backend is not None
        return backend

    def _read_account(self, account: str) -> str | None:
        if account in self._deleted:
            return None
        if account in self._memory:
            return self._memory[account]
        backend = self._backend()
        if backend is not None:
            try:
                return backend.get_password(self.service, account) or None
            except Exception:
                self.persistent = False
        return None

    def get(self, owner_id: str, provider: str, credential_id: str) -> str | None:
        return self._read_account(_account(owner_id, provider))

    def put(self, owner_id: str, provider: str, credential_id: str, secret: str) -> None:
        account = _account(owner_id, provider)
        self._deleted.discard(account)
        backend = self._backend()
        if backend is not None:
            try:
                backend.set_password(self.service, account, secret)
                self._memory.pop(account, None)
                return
            except Exception:
                self.persistent = False
        self._memory[account] = secret

    def delete(self, owner_id: str, provider: str, credential_id: str) -> None:
        account = _account(owner_id, provider)
        self._deleted.add(account)
        self._memory.pop(account, None)
        backend = self._backend()
        if backend is not None:
            try:
                backend.delete_password(self.service, account)
            except Exception:
                self.persistent = False

    # One-time move from the old account name. The legacy item is removed only
    # after the new item and its row exist, so a failed write keeps the old key.

    def legacy(self, provider: str) -> str | None:
        return self._read_account(provider)

    def delete_legacy(self, provider: str) -> None:
        self._deleted.add(provider)
        backend = self._backend()
        if backend is not None:
            try:
                backend.delete_password(self.service, provider)
                return
            except Exception:
                self.persistent = False
        self._memory.pop(provider, None)

    def move_legacy(self, store: Any, owner_id: str, provider: str) -> bool:
        """Copy an old `<provider>` key into the store once; True when it moved."""
        if store.credential_id(owner_id, provider) is not None:
            return False
        secret = self.legacy(provider)
        if not secret:
            return False
        store.put(owner_id, provider, secret, None)
        self.delete_legacy(provider)
        return True


def _os_backend() -> Any:
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    if sys.platform == "linux":
        from keyring.backends.SecretService import Keyring
        return Keyring() if Keyring.priority > 0 else None
    return None


__all__ = ["KeyringVault"]
