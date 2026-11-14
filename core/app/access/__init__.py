"""Session, CSRF and origin checks. Implemented by the access lane."""

from __future__ import annotations

from collections.abc import Mapping

from app.ports import AppSettings
from app.schemas.api import (
    ApiKeyRequest,
    CredentialState,
    CsrfResponse,
    PairRequest,
    PairResponse,
)


class SessionGuard:
    """Checks cookie, CSRF token and Origin for state-changing requests."""

    def check(self, headers: dict[str, str], *, mutate: bool) -> None:
        raise NotImplementedError

    def csrf(self, headers: Mapping[str, str]) -> CsrfResponse:
        """Re-issue the CSRF token for a valid session from the same origin."""
        raise NotImplementedError

    def pair(self, body: PairRequest) -> PairResponse:
        raise NotImplementedError

    def set_llm_credentials(self, body: ApiKeyRequest) -> None:
        raise NotImplementedError

    def llm_credentials(self) -> CredentialState:
        raise NotImplementedError

    def clear_llm_credentials(self) -> None:
        raise NotImplementedError


def create(settings: AppSettings) -> SessionGuard:
    return SessionGuard()
