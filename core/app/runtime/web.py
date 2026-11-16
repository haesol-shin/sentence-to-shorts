"""Serve the built frontend files next to the API from the same origin.

Everything below `/api/` and the API documentation paths belong to the app and pass
through untouched. Other GET and HEAD requests get a file of the web folder, or the
index page for a path without an extension so the single-page app can route it. The
files are public, but the Host header is still checked so the page is not served to a
rebinding name, and the caller supplies the response headers of the API.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path
from urllib.parse import unquote

from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

API_PREFIXES = ("/api/", "/docs", "/openapi.json")
INDEX = "index.html"


class StaticSite:
    def __init__(
        self,
        app: ASGIApp,
        web_dir: Path,
        *,
        hosts: Collection[str],
        headers: Mapping[str, str],
    ) -> None:
        self.app = app
        self.root = web_dir.resolve()
        self.hosts = frozenset(host.lower() for host in hosts)
        self.headers = dict(headers)

    def _file_for(self, path: str) -> Path | None:
        relative = unquote(path).lstrip("/")
        parts = relative.split("/") if relative else []
        unsafe = ("..", ".")
        if any(part in unsafe or any(c in part for c in "\\\0:") for part in parts):
            return None
        candidate = self.root.joinpath(*parts) if parts else self.root / INDEX
        if candidate.is_dir():
            candidate = candidate / INDEX
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        if self.root not in resolved.parents or not resolved.is_file():
            return None
        return resolved

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path.startswith(API_PREFIXES):
            await self.app(scope, receive, send)
            return
        host = next(
            (value.decode("latin-1").lower() for key, value in scope["headers"] if key == b"host"),
            "",
        )
        response: Response
        if host not in self.hosts:
            response = PlainTextResponse("Forbidden", status_code=403)
        else:
            found = self._file_for(path)
            if found is None and "." not in path.rsplit("/", 1)[-1]:
                found = self._file_for("/" + INDEX)
            if found is None:
                response = PlainTextResponse("Not found", status_code=404)
            else:
                response = FileResponse(found)
                if found.name == INDEX:
                    response.headers["Cache-Control"] = "no-cache"
        for name, value in self.headers.items():
            response.headers[name] = value
        await response(scope, receive, send)
