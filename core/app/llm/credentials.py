"""Explicit OS credential storage with an in-memory-only fallback.

Only Windows Credential Manager and Linux Secret Service are selected. A missing
OS store never enables a plaintext backend. Keys are never written to app state.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any


class Credentials:
    def __init__(self, service: str, account: str, *, env_var: str | None = None,
                 backend_factory: Callable[[], Any] | None = None) -> None:
        self.service = service
        self.account = account
        self.env_var = env_var
        self._memory: str | None = None
        self._factory = backend_factory or _os_backend
        self.persistent = False
        self._deleted = False

    def _backend(self) -> Any:
        try:
            backend = self._factory()
        except Exception:
            backend = None
        self.persistent = backend is not None
        return backend

    def read(self) -> str | None:
        if self._deleted:
            return None
        if self._memory is not None:
            return self._memory
        if self.env_var and os.environ.get(self.env_var):
            return os.environ[self.env_var]
        backend = self._backend()
        if backend is not None:
            try:
                return backend.get_password(self.service, self.account) or None
            except Exception:
                self.persistent = False
        return None

    def set(self, value: str) -> None:
        self._deleted = False
        backend = self._backend()
        if backend is not None:
            try:
                backend.set_password(self.service, self.account, value)
                self._memory = None
                return
            except Exception:
                self.persistent = False
        self._memory = value

    def delete(self) -> None:
        self._memory = None
        backend = self._backend()
        if backend is not None:
            try:
                backend.delete_password(self.service, self.account)
            except Exception:
                self.persistent = False

        self._deleted = True


def _os_backend() -> Any:
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    if sys.platform == "linux":
        from keyring.backends.SecretService import Keyring
        return Keyring() if Keyring.priority > 0 else None
    return None


def credential_source(settings: Any, provider: str, *, env_var: str | None = None) -> Credentials:
    return Credentials(settings.brand.app_id, provider, env_var=env_var)
