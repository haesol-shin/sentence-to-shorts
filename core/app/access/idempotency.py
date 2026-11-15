"""Idempotency-Key handling for the routes that declare the header (CONTRACTS 3).

The request body is read once before routing. JSON bodies are hashed as canonical
JSON. A multipart body is spooled to a temporary file while the `file` part is hashed,
and the upload limit cuts it off with 413 as soon as it is exceeded. The router then
reads the same bytes from the spool. A repeat with the same key and digest gets the
stored response back without reaching the router.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import IO, Any, BinaryIO

from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response
from starlette.routing import compile_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.access.instance import acquire_instance_lock
from app.access.middleware import DETAILS, Reject
from app.ports import AppError, canonical_digest, canonical_json
from app.storage.idempotency import (
    KEY_PATTERN,
    IdempotencyInProgress,
    SqliteIdempotencyStore,
)
from app.storage.sqlite import Database

SPOOL_MEMORY_BYTES = 1 << 20
REPLAY_CHUNK_BYTES = 1 << 16
JSON_BODY_MAX_BYTES = 1 << 20
FORM_OVERHEAD_BYTES = 1 << 20
FIELD_BYTES_MAX = 1 << 16
FILE_FIELD = "file"


@dataclass(frozen=True)
class KeyedRoute:
    """A route that takes `Idempotency-Key`, with its upload limit when it is multipart."""

    methods: frozenset[str]
    path: re.Pattern[str]
    upload_limit: int | None


class IdempotencyGate:
    """The state.db handle and the key store used by the middleware."""

    def __init__(
        self, db: Database, store: SqliteIdempotencyStore, instance_lock: BinaryIO
    ) -> None:
        self._db = db
        self.store = store
        self._instance_lock = instance_lock

    @classmethod
    def open(cls, state_db: Path, *, ttl_hours: int) -> IdempotencyGate:
        instance_lock = acquire_instance_lock(state_db)
        db = None
        try:
            db = Database.open(state_db)
            store = SqliteIdempotencyStore(db, ttl_hours=ttl_hours)
            store.drop_pending()
            store.purge_expired()
            return cls(db, store, instance_lock)
        except BaseException:
            try:
                if db is not None:
                    db.close()
            finally:
                instance_lock.close()
            raise

    def close(self) -> None:
        try:
            self._db.close()
        finally:
            self._instance_lock.close()


class _MultipartDigest:
    """Parser callbacks that hash the `file` part and collect the other fields."""

    def __init__(self, file_limit: int) -> None:
        self._file_limit = file_limit
        self._file: Any = None
        self._file_bytes = 0
        self._field_bytes = 0
        self._fields: dict[str, str] = {}
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._disposition = b""
        self._part: str | None = None
        self._buffer = bytearray()
        self._finished = False

    def callbacks(self) -> dict[str, Any]:
        return {
            "on_part_begin": self._part_begin,
            "on_header_field": self._header_field,
            "on_header_value": self._header_value_data,
            "on_header_end": self._header_end,
            "on_headers_finished": self._headers_finished,
            "on_part_data": self._part_data,
            "on_part_end": self._part_end,
            "on_end": self._end,
        }

    def _end(self) -> None:
        self._finished = True

    def _part_begin(self) -> None:
        self._disposition = b""
        self._part = None
        self._buffer = bytearray()

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def _header_value_data(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def _header_end(self) -> None:
        if bytes(self._header_name).lower() == b"content-disposition":
            self._disposition = bytes(self._header_value)
        self._header_name = bytearray()
        self._header_value = bytearray()

    def _headers_finished(self) -> None:
        _, options = parse_options_header(self._disposition)
        raw = options.get(b"name")
        if raw is None:
            raise AppError("validation_failed")
        name = raw.decode("utf-8", errors="strict")
        if name == FILE_FIELD:
            if self._file is not None:
                raise AppError("validation_failed")
            self._file = hashlib.sha256()
        elif name in self._fields:
            raise AppError("validation_failed")
        self._part = name

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        size = end - start
        if self._part == FILE_FIELD:
            self._file_bytes += size
            if self._file_bytes > self._file_limit:
                raise AppError("payload_too_large")
            self._file.update(data[start:end])
            return
        self._field_bytes += size
        if self._field_bytes > FIELD_BYTES_MAX:
            raise AppError("payload_too_large")
        self._buffer += data[start:end]

    def _part_end(self) -> None:
        if self._part is not None and self._part != FILE_FIELD:
            self._fields[self._part] = bytes(self._buffer).decode("utf-8", errors="strict")
        self._part = None

    def digest(self) -> str:
        if self._file is None or not self._finished:
            raise AppError("validation_failed")
        text = self._file.hexdigest() + canonical_json(self._fields).decode("utf-8")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _chunks(receive: Receive) -> AsyncIterator[bytes]:
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise ClientDisconnect()
        chunk = message.get("body", b"")
        if chunk:
            yield chunk
        if not message.get("more_body", False):
            return


async def _multipart_digest(
    receive: Receive, headers: Headers, spool: IO[bytes], file_limit: int
) -> str:
    raw_limit = file_limit + FORM_OVERHEAD_BYTES
    length = headers.get("content-length", "")
    if length.isdigit() and int(length) > raw_limit:
        raise AppError("payload_too_large")
    _, options = parse_options_header(headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if not boundary:
        raise AppError("validation_failed")
    state = _MultipartDigest(file_limit)
    parser = MultipartParser(boundary, state.callbacks())  # type: ignore[arg-type]
    total = 0
    try:
        async for chunk in _chunks(receive):
            total += len(chunk)
            if total > raw_limit:
                raise AppError("payload_too_large")
            spool.write(chunk)
            parser.write(chunk)
        parser.finalize()
    except (MultipartParseError, UnicodeDecodeError) as error:
        raise AppError("validation_failed") from error
    return state.digest()


def _reject_constant(text: str) -> Any:
    raise ValueError(f"unsupported JSON constant {text}")


async def _json_digest(receive: Receive, spool: IO[bytes]) -> str:
    total = 0
    async for chunk in _chunks(receive):
        total += len(chunk)
        if total > JSON_BODY_MAX_BYTES:
            raise AppError("payload_too_large")
        spool.write(chunk)
    spool.seek(0)
    body = spool.read()
    if not body:
        return canonical_digest({})
    try:
        value = json.loads(body, parse_constant=_reject_constant)
        return canonical_digest(value)
    except (ValueError, TypeError, UnicodeDecodeError) as error:
        raise AppError("validation_failed") from error


def _replay(spool: IO[bytes], receive: Receive) -> Receive:
    size = spool.seek(0, 2)
    spool.seek(0)
    done = False

    async def replayed() -> Message:
        nonlocal done
        if done:
            return await receive()
        chunk = spool.read(REPLAY_CHUNK_BYTES)
        more = spool.tell() < size
        done = not more
        return {"type": "http.request", "body": chunk, "more_body": more}

    return replayed


def _stored_response(status: int, body: Any) -> Response:
    if body is None:
        return Response(status_code=status)
    media_type = "application/problem+json" if status >= 400 else "application/json"
    return JSONResponse(content=body, status_code=status, media_type=media_type)


class IdempotencyMiddleware:
    """Reserve the key, run the request once and store its response."""

    def __init__(
        self, app: ASGIApp, *, routes: Sequence[KeyedRoute], reject: Reject
    ) -> None:
        self.app = app
        self.routes = tuple(routes)
        self.reject = reject

    def _route(self, scope: Scope) -> KeyedRoute | None:
        if scope["type"] != "http":
            return None
        for route in self.routes:
            if scope["method"] in route.methods and route.path.match(scope["path"]):
                return route
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        route = self._route(scope)
        if route is None:
            await self.app(scope, receive, send)
            return
        gate: IdempotencyGate = scope["app"].state.idempotency
        headers = Headers(scope=scope)
        key = headers.get("idempotency-key", "")
        name = f"{scope['method']} {scope['path']}"
        cache = scope["app"].state.runtime.settings.cache_dir
        cache.mkdir(parents=True, exist_ok=True)
        with SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, dir=cache) as spool:
            try:
                if not KEY_PATTERN.fullmatch(key):
                    raise AppError("validation_failed")
                digest = await self._digest(route, headers, receive, spool)
                stored = await run_in_threadpool(gate.store.begin, key, name, digest)
            except ClientDisconnect:
                return
            except IdempotencyInProgress:
                await self._reject(scope, receive, send, "rate_limited")
                return
            except AppError as error:
                await self._reject(scope, receive, send, error.code)
                return
            if stored is not None:
                await _stored_response(stored.status, stored.body)(scope, receive, send)
                return
            await self._run_once(scope, _replay(spool, receive), send, gate, (key, name, digest))

    async def _digest(
        self, route: KeyedRoute, headers: Headers, receive: Receive, spool: IO[bytes]
    ) -> str:
        content_type = headers.get("content-type", "").lower()
        if route.upload_limit is not None and not content_type.startswith("multipart/form-data"):
            raise AppError("unsupported_media")
        if content_type.startswith("multipart/form-data"):
            if route.upload_limit is None:
                raise AppError("validation_failed")
            return await _multipart_digest(receive, headers, spool, route.upload_limit)
        return await _json_digest(receive, spool)

    async def _reject(self, scope: Scope, receive: Receive, send: Send, code: str) -> None:
        await self.reject(scope, code, DETAILS[code])(scope, receive, send)

    async def _run_once(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        gate: IdempotencyGate,
        record: tuple[str, str, str],
    ) -> None:
        messages: list[Message] = []

        async def capture(message: Message) -> None:
            messages.append(message)

        try:
            await self.app(scope, receive, capture)
            await run_in_threadpool(self._record, gate.store, record, messages)
        except BaseException:
            await run_in_threadpool(gate.store.abort, *record)
            raise
        for message in messages:
            await send(message)

    @staticmethod
    def _record(
        store: SqliteIdempotencyStore, record: tuple[str, str, str], messages: list[Message]
    ) -> None:
        start = next((m for m in messages if m["type"] == "http.response.start"), None)
        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        status = int(start["status"]) if start else 500
        if status >= 500:
            store.abort(*record)
            return
        try:
            value = json.loads(body) if body else None
        except ValueError:
            store.abort(*record)
            return
        store.complete(*record, status, value)


def keyed_routes(
    document: Mapping[str, Any], upload_limits: Mapping[str, int]
) -> list[KeyedRoute]:
    """Read public header metadata, including FastAPI's lazy included routers."""
    found = []
    for path, operations in document["paths"].items():
        methods = {
            method.upper()
            for method, operation in operations.items()
            if isinstance(operation, dict)
            and any(
                param.get("in") == "header" and param.get("name") == "Idempotency-Key"
                for param in operation.get("parameters", [])
            )
        }
        if methods:
            found.append(
                KeyedRoute(
                    methods=frozenset(methods),
                    path=compile_path(path)[0],
                    upload_limit=upload_limits.get(path),
                )
            )
    return found


__all__ = ["IdempotencyGate", "IdempotencyMiddleware", "KeyedRoute", "keyed_routes"]
