"""A loopback OpenAI-compatible endpoint that replays the recorded LLM responses.

The release smoke drives a real user path through the installed app. The app's `dev`
profile talks Chat Completions to `APP_LLM_BASE_URL`; this stub answers those calls from
the recordings under `fixtures/llm/<task>/*.json` of the repository checkout, so the run
needs no account and no network. Standard library only: the smoke must stay runnable
without the app's packages.

A request matches a recording when the system text, the user text parts and the output
schema agree with the recorded request. Entity ids are random per run, so they are named
by their order of first appearance on both sides, and the recorded ids are bound to the
live ones in the reply. The id pattern and the two helpers below deliberately repeat
`app.llm.providers.fixture.adapter`, and the schema instruction that the app appends to the
system text, when the app adds one, is stripped again (the stub may not import the app);
tests build the app's real request for every shipped recording and compare. Route, token
limit and model name are not part of the match: they are not on the wire in a form the recordings could constrain.

A request without a recording is answered with HTTP 400 and kept in `unmatched`, so the
smoke fails naming the task instead of hanging on an endless retry.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "llm"
MAX_BODY_BYTES = 8 * 1024 * 1024
DATA_URL = "data:image/png;base64,"
_ENTITY_ID = re.compile(r"(?<![0-9a-z_])[a-z]{1,2}_[0-7][0-9a-hjkmnp-tv-z]{25}(?![0-9a-z_])")


def id_order(texts: Iterable[str | None]) -> list[str]:
    seen: dict[str, None] = {}
    for text in texts:
        if text is not None:
            for found in _ENTITY_ID.finditer(text):
                seen.setdefault(found.group())
    return list(seen)


def name_ids(text: str, order: list[str]) -> str:
    index = {entity_id: number for number, entity_id in enumerate(order)}
    return _ENTITY_ID.sub(lambda found: f"<id:{index[found.group()]}>", text)


def bind_ids(text: str, mapping: dict[str, str]) -> str:
    """Swap recorded ids for live ones in one pass so ids never chain."""
    return _ENTITY_ID.sub(lambda found: mapping.get(found.group(), found.group()), text)


def schema_instruction(schema: Any) -> str:
    """The text the app appends to the system message when a request has an output schema."""
    text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return (
        "Return one JSON object that validates against this schema, "
        "with no Markdown code fence and no text outside the object:\n" + text
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _key(system: str, parts: list[dict[str, str]], schema: Any) -> str:
    return hashlib.sha256(_canonical([system, parts, schema]).encode("utf-8")).hexdigest()


def recorded_key(request: dict[str, Any]) -> str:
    """Match key of a recorded request, from its stored text and schema."""
    parts = request["parts"]
    order = id_order(part.get("text") for part in parts)
    normalized: list[dict[str, str]] = []
    for part in parts:
        item = {"kind": part["kind"]}
        if part.get("text") is not None:
            item["text"] = name_ids(part["text"], order)
        if part.get("png_sha256") is not None:
            item["png_sha256"] = part["png_sha256"]
        normalized.append(item)
    return _key(request["system"], normalized, request.get("output_schema"))


class WireError(ValueError):
    """The request is not the Chat Completions shape the app sends."""


def wire_parts(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]], Any]:
    """Recorded-form system text, raw user parts (text or png digest) and output schema."""
    try:
        system, user = payload["messages"]
        if system["role"] != "system" or user["role"] != "user":
            raise WireError("unexpected message roles")
        parts: list[dict[str, Any]] = []
        for part in user["content"]:
            if part["type"] == "text":
                parts.append({"kind": "text", "text": part["text"]})
            elif part["type"] == "image_url" and part["image_url"]["url"].startswith(DATA_URL):
                raw = base64.b64decode(part["image_url"]["url"][len(DATA_URL):])
                parts.append({"kind": "png", "png_sha256": hashlib.sha256(raw).hexdigest()})
            else:
                raise WireError("unsupported content part")
        schema = None
        if "response_format" in payload:
            schema = payload["response_format"]["json_schema"]["schema"]
        text = system["content"]
        if schema is not None:
            # The recording holds the system text without the schema, which the app adds.
            tail = "\n\n" + schema_instruction(schema)
            if text.endswith(tail):
                text = text[: -len(tail)]
        return text, parts, schema
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, WireError):
            raise
        raise WireError("not a chat completions request") from None


def wire_key(system: str, parts: list[dict[str, Any]], schema: Any) -> tuple[str, list[str]]:
    """Match key of a live request and its entity ids in order of first appearance."""
    order = id_order(part.get("text") for part in parts)
    normalized = []
    for part in parts:
        item = {"kind": part["kind"]}
        if part.get("text") is not None:
            item["text"] = name_ids(part["text"], order)
        if part.get("png_sha256") is not None:
            item["png_sha256"] = part["png_sha256"]
        normalized.append(item)
    return _key(system, normalized, schema), order


class Recording:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        request = data["request"]
        self.name = f"{data['task']}/{path.stem[:12]}"
        self.task = str(data["task"])
        self.text = str(data["text"])
        self.system = str(request["system"])
        self.ids = id_order(part.get("text") for part in request["parts"])
        self.key = recorded_key(request)


def load_recordings(root: Path) -> list[Recording]:
    found = [
        Recording(path, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(root.glob("*/*.json"))
    ]
    if not found:
        raise FileNotFoundError(f"no recordings under {root}")
    return found


class RecordedLlm:
    """The stub server. `served` names each recording used; `unmatched` holds refusals."""

    def __init__(self, root: Path = FIXTURE_ROOT) -> None:
        self.recordings = load_recordings(root)
        # The task is not on the wire, so two recordings that differ only by task share a
        # key (the synthetic ones do). The shipped flow never hits one; the stub refuses it.
        self.by_key: dict[str, list[Recording]] = {}
        for recording in self.recordings:
            self.by_key.setdefault(recording.key, []).append(recording)
        self.served: list[str] = []
        self.unmatched: list[str] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def listen(self) -> None:
        """Bind a loopback port and serve on a thread; `base_url` names it."""
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                owner._handle(self)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}/v1"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def answer(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """Status and JSON body for one decoded request. Pure apart from the logs."""
        try:
            system, parts, schema = wire_parts(payload)
        except WireError as error:
            return self._refuse(f"malformed request: {error}")
        key, live_ids = wire_key(system, parts, schema)
        matches = self.by_key.get(key, [])
        if len(matches) > 1:
            tasks = sorted(match.task for match in matches)
            return self._refuse(f"ambiguous: the recordings of {tasks} share this wire request")
        recording = matches[0] if matches else None
        if recording is None:
            same_system = sorted({r.task for r in self.recordings if r.system == system})
            if same_system:
                reason = (
                    f"no recording matches: the system text belongs to {same_system} but the "
                    "user parts or the output schema differ"
                )
            else:
                reason = "no recording matches: the system text is unknown"
            first = next((part["text"] for part in parts if part.get("text")), "")
            return self._refuse(f"{reason}; first text starts {first[:60]!r}")
        mapping = dict(zip(recording.ids, live_ids, strict=True))
        text = bind_ids(recording.text, mapping)
        with self._lock:
            self.served.append(recording.name)
        prompt = sum(len(part.get("text") or "") for part in parts) // 4 + 1
        return 200, {
            "id": "chatcmpl-recorded",
            "object": "chat.completion",
            "model": "recorded",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": len(text) // 4 + 1,
                "total_tokens": prompt + len(text) // 4 + 1,
            },
        }

    def _refuse(self, reason: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            self.unmatched.append(reason)
        return 400, {"error": {"message": reason, "code": "smoke_unmatched"}}

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length") or 0)
        if handler.path.rstrip("/") != "/v1/chat/completions" or length > MAX_BODY_BYTES:
            status, body = self._refuse(f"unexpected request: POST {handler.path[:40]}")
        else:
            try:
                payload = json.loads(handler.rfile.read(length))
            except ValueError:
                status, body = self._refuse("the request body is not JSON")
            else:
                status, body = self.answer(payload)
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def close(self) -> None:
        if self._server is None or self._thread is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def start(root: Path = FIXTURE_ROOT) -> RecordedLlm:
    stub = RecordedLlm(root)
    stub.listen()
    return stub
