"""Pairing, session cookie, CSRF, Host and Origin checks (CONTRACTS 3 and 13.2).

Sessions and pairing codes live in memory only, so a restart signs every browser out.
`check` decides whether a request may reach the routers; the ASGI wiring is in
`app.access.middleware`.
"""

from __future__ import annotations

import hmac
import ipaddress
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.requests import cookie_parser

from app.ports import AppError, AppSettings
from app.schemas.api import (
    ApiKeyRequest,
    CredentialState,
    CsrfResponse,
    PairRequest,
    PairResponse,
)
from app.schemas.common import Language

API_PREFIX = "/api/v1"
PAIR_PATH = f"{API_PREFIX}/session/pair"
PUBLIC_REQUESTS = frozenset({("GET", f"{API_PREFIX}/health"), ("POST", PAIR_PATH)})
CREDENTIAL_PATHS = frozenset({f"{API_PREFIX}/credentials/llm"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
WILDCARD_BINDS = frozenset({"", "0.0.0.0", "::", "[::]"})

PAIR_CODE_TTL_S = 300.0
PAIR_FAILURE_LIMIT = 5
PAIR_FAILURE_WINDOW_S = 60.0

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

# The pair route returns only the JSON body; the session cookie for that response
# travels to the access middleware through this per-request slot.
ISSUED_COOKIES: ContextVar[list[str] | None] = ContextVar("issued_cookies", default=None)


@dataclass(frozen=True)
class Session:
    id: str
    csrf_token: str


def _host_literal(bind_host: str) -> str:
    try:
        address = ipaddress.ip_address(bind_host)
    except ValueError:
        return bind_host.lower()
    return f"[{address}]" if address.version == 6 else str(address)


def _is_loopback(client: str | None) -> bool:
    if client is None:
        return False
    try:
        return ipaddress.ip_address(client).is_loopback
    except ValueError:
        return False


class SessionGuard:
    """Owns pairing codes and sessions and checks every request against them."""

    def __init__(self, settings: AppSettings, *, clock: Callable[[], float] = time.monotonic):
        self._settings = settings
        self._clock = clock
        self._lock = threading.Lock()
        self._code: str | None = None
        self._code_expires = 0.0
        self._failures: deque[float] = deque()
        self._sessions: dict[str, Session] = {}
        self.cookie_name = f"session_{settings.port}"
        names = list(LOOPBACK_NAMES)
        if settings.lan and settings.bind_host not in WILDCARD_BINDS:
            names.append(_host_literal(settings.bind_host))
        port = settings.port
        hosts = {f"{name}:{port}" for name in names}
        if port == 80:
            hosts.update(names)
        self._hosts = frozenset(hosts)
        self.issue_pairing_code()

    # Pairing and sessions

    def issue_pairing_code(self) -> str:
        """A new one-time code for the launcher to show. It replaces the previous code."""
        code = secrets.token_urlsafe(24)
        with self._lock:
            self._code = code
            self._code_expires = self._clock() + PAIR_CODE_TTL_S
        return code

    def pair(self, body: PairRequest) -> PairResponse:
        with self._lock:
            now = self._clock()
            while self._failures and self._failures[0] <= now - PAIR_FAILURE_WINDOW_S:
                self._failures.popleft()
            if len(self._failures) >= PAIR_FAILURE_LIMIT:
                raise AppError("rate_limited")
            code = self._code
            if code is None or now >= self._code_expires or not hmac.compare_digest(
                code.encode(), body.code.encode()
            ):
                self._failures.append(now)
                raise AppError("pair_invalid")
            self._code = None
            session = Session(id=secrets.token_urlsafe(32), csrf_token=secrets.token_urlsafe(32))
            self._sessions[session.id] = session
        issued = ISSUED_COOKIES.get()
        if issued is not None:
            issued.append(
                f"{self.cookie_name}={session.id}; Path=/; HttpOnly; SameSite=Strict"
            )
        return PairResponse(
            csrf_token=session.csrf_token,
            profile=self._settings.profile,  # type: ignore[arg-type]
            deployment=self._settings.deployment,  # type: ignore[arg-type]
            ui_language=Language.ko,
        )

    def session(self, cookie_header: str | None) -> Session | None:
        if not cookie_header:
            return None
        value = cookie_parser(cookie_header).get(self.cookie_name)
        if not value:
            return None
        with self._lock:
            return self._sessions.get(value)

    def csrf(self, headers: Mapping[str, str]) -> CsrfResponse:
        """Re-issue the CSRF token for a valid session from the same origin."""
        session = self.session(headers.get("cookie"))
        if session is None:
            raise AppError("unauthenticated")
        origin = headers.get("origin")
        expected = f"http://{headers.get('host', '').lower()}"
        if origin is not None and origin != expected:
            raise AppError("forbidden_origin")
        # Plain HTTP LAN browsers may omit both Origin and Fetch Metadata on GET.
        # Reject contrary evidence when present; otherwise the Strict session cookie
        # and the browser same-origin policy protect this read-only token response.
        site = headers.get("sec-fetch-site")
        if site is not None and site != "same-origin":
            raise AppError("forbidden_origin")
        return CsrfResponse(csrf_token=session.csrf_token)

    # Request checks

    def check(
        self,
        headers: Mapping[str, str],
        *,
        method: str,
        path: str,
        client: str | None,
    ) -> None:
        """Raise AppError with the problem code when the request must not reach a router.

        `headers` has lower-case names and the first value of each header.
        """
        host = headers.get("host", "").lower()
        if host not in self._hosts:
            raise AppError("forbidden_host")
        mutate = method not in SAFE_METHODS
        self._check_origin(headers.get("origin"), host, required=mutate)
        if (method, path) in PUBLIC_REQUESTS:
            return
        session = self.session(headers.get("cookie"))
        if session is None:
            raise AppError("unauthenticated")
        if mutate:
            token = headers.get("x-csrf-token", "")
            if not hmac.compare_digest(token.encode(), session.csrf_token.encode()):
                raise AppError("csrf_failed")
            if path in CREDENTIAL_PATHS and not self._from_loopback(host, client):
                raise AppError("loopback_only")

    def _check_origin(self, origin: str | None, host: str, *, required: bool) -> None:
        if origin is None:
            if required:
                raise AppError("forbidden_origin")
            return
        if origin != f"http://{host}":
            raise AppError("forbidden_origin")

    def _from_loopback(self, host: str, client: str | None) -> bool:
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return name in LOOPBACK_NAMES and _is_loopback(client)

    # Credentials: the loopback rule is enforced in `check`; storage is not built yet.

    def set_llm_credentials(self, body: ApiKeyRequest) -> None:
        raise NotImplementedError

    def llm_credentials(self) -> CredentialState:
        raise NotImplementedError

    def clear_llm_credentials(self) -> None:
        raise NotImplementedError


def create(settings: AppSettings) -> SessionGuard:
    return SessionGuard(settings)


__all__ = [
    "ISSUED_COOKIES",
    "SECURITY_HEADERS",
    "Session",
    "SessionGuard",
    "create",
]
