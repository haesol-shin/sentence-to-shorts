"""ASGI wiring of the access checks: every request passes `SessionGuard.check` first."""

from __future__ import annotations

from collections.abc import Callable

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.access import ISSUED_COOKIES, SECURITY_HEADERS
from app.ports import AppError

Reject = Callable[[Scope, str, str], Response]
"""Build the problem response for an error code and a detail sentence."""

DETAILS = {
    "forbidden_host": "The Host header is not allowed.",
    "forbidden_origin": "The request origin is not the app origin.",
    "unauthenticated": "The request has no valid session.",
    "csrf_failed": "The CSRF token is missing or wrong.",
    "loopback_only": "Credentials can only be changed from this computer.",
    "validation_failed": "The request headers do not match the contract.",
    "payload_too_large": "The upload is larger than the allowed size.",
    "unsupported_media": "This upload endpoint requires multipart/form-data.",
    "idempotency_mismatch": "The Idempotency-Key was used for another request.",
    "rate_limited": "A request with this Idempotency-Key is still running.",
}
SINGLE_HEADERS = ("host", "origin", "cookie", "x-csrf-token", "idempotency-key")


def secure_send(send: Send, cookies: list[str] | None = None) -> Send:
    """Add the security headers, and any session cookie issued by pairing, to the response."""

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = MutableHeaders(scope=message)
            for name, value in SECURITY_HEADERS.items():
                headers[name] = value
            if cookies and message["status"] == 200:
                for cookie in cookies:
                    headers.append("Set-Cookie", cookie)
        await send(message)

    return wrapped


class AccessMiddleware:
    """Reject requests before routing unless Host, Origin, session and CSRF all match."""

    def __init__(self, app: ASGIApp, *, reject: Reject) -> None:
        self.app = app
        self.reject = reject

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            # No WebSocket endpoint exists; refuse the handshake instead of routing it.
            await send({"type": "websocket.close", "code": 1008})
            return
        guard = scope["app"].state.runtime.access
        raw = Headers(scope=scope)
        try:
            if any(len(raw.getlist(name)) > 1 for name in SINGLE_HEADERS):
                raise AppError("validation_failed")
            client = scope.get("client")
            guard.check(
                {key: raw[key] for key in raw.keys()},
                method=scope["method"],
                path=scope["path"],
                client=client[0] if client else None,
            )
        except AppError as error:
            response = self.reject(scope, error.code, DETAILS[error.code])
            await response(scope, receive, secure_send(send))
            return
        cookies: list[str] = []
        token = ISSUED_COOKIES.set(cookies)
        try:
            await self.app(scope, receive, secure_send(send, cookies))
        finally:
            ISSUED_COOKIES.reset(token)
