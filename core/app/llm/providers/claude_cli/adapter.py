"""Optional provider that runs the unmodified official Claude CLI in print mode.

The CLI process gets a fresh empty directory under CACHE_DIR, a small
environment allowlist that keeps HOME for its own login, and only the isolation
flags whose presence was verified in its ``--help`` output. Prompts, the output
schema and untrusted parts travel on stdin as one JSON user message: the trusted
system text is a separate content block from every data part, and no prompt or
schema is placed in argv. The verified help has no stdin or file channel for a
system prompt, so a separate first content block is the available boundary.

``png`` parts travel as ``image`` content blocks in the same stream-json user
message, the shape the official Agent SDK documents for a follow-up message with
an image. They are data, never instructions; the shared layer already refuses
more than eight frames per call (CONTRACTS 10.4). There is also no safe
non-generating login probe, so ``auth_state`` reports ``missing`` when the
executable is absent and otherwise caches the outcome observed by ``complete``;
it starts as ``unknown``.

The verified help has no max-output-token flag and no verified environment
control for one. The provider therefore sends the request budget as a trusted
instruction and fails with ``llm_invalid_output`` when the CLI reports more
output tokens than that budget. When the CLI omits output usage, the budget
cannot be enforced and only the instruction remains.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.llm.common import (
    BaseLlm,
    ProviderError,
    ProviderReply,
    ResolvedRoute,
    check_active,
    settings_options,
    token_count,
)
from app.llm.providers.claude_cli.process import CliProcessResult, run
from app.llm.schema_prompt import schema_instruction
from app.ports import AppSettings, CancelToken, CredentialResolver, LlmRequest

PROVIDER = "claude_cli"
MINIMUM_VERSION = (2, 1, 325)
PROBE_TIMEOUT_S = 20.0
MAX_STDOUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024

# Every flag below is needed to remove a capability. Permission bypass flags are
# deliberately absent. The exact expected list belongs to the test evidence.
REQUIRED_FLAGS = (
    "--print",
    "--safe-mode",
    "--restricted",
    "--tools",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--permission-prompts",
    "--output-format",
    "--input-format",
    "--verbose",
    "--effort",
    "--model",
)

# HOME and USERPROFILE are kept so the CLI can find its own login; API key,
# OAuth and cloud credential variables are never included.
ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_COLOR",
    }
)
SECRET_ENV_MARKERS = (
    "ANTHROPIC",
    "CLAUDE",
    "OPENAI",
    "AWS",
    "AZURE",
    "GOOGLE",
    "OAUTH",
    "TOKEN",
    "API_KEY",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
)
TOOL_ACTIVITY_TYPES = frozenset(
    {"tool_use", "tool_result", "server_tool_use", "mcp_tool_use"}
)
AUTH_MARKERS = (
    "authentication",
    "authenticate",
    "not logged in",
    "log in",
    "login",
    "logged out",
    "unauthorized",
    "oauth",
    "api key",
    "credential",
    "expired",
    " 401",
    " 403",
)
QUOTA_MARKERS = ("quota", "credit", "usage limit", "billing", "max_budget", " 402")
RATE_MARKERS = ("rate limit", "rate-limit", "too many requests", " 429")
TIMEOUT_MARKERS = ("timeout", "timed out", "deadline")
REFUSAL_MARKERS = (
    "refus",
    "declin",
    "can't help",
    "cannot help",
    "unable to help",
    "not able to help",
    "permission",
)
CONNECTION_MARKERS = (
    "connection",
    "network",
    "overloaded",
    "unavailable",
    "try again",
    " 500",
    " 502",
    " 503",
    " 504",
)
INVALID_MARKERS = ("invalid json", "schema", "structured output", "could not parse")
# Argument errors reported before any request; retrying them cannot succeed.
USAGE_MARKERS = ("requires", "unknown option", "invalid option", "error: option")
VERSION_PATTERN = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")


class ClaudeCliLlm(BaseLlm):
    provider = PROVIDER

    def __init__(
        self,
        settings: AppSettings,
        *,
        routing: Any = None,
        executable: str | Path | None = None,
    ) -> None:
        if settings.profile != "dev":
            raise ValueError("claude_cli is only available in the dev profile")
        super().__init__(settings, routing=routing)
        options = settings_options(settings, self.provider)
        selected = executable
        if selected is None and isinstance(options, Mapping):
            selected = options.get("executable")
        self.executable = str(selected) if selected else "claude"
        self._probe_lock = threading.Lock()
        self._probe_ready = False
        self._cli_version: str | None = None

    @property
    def cli_version(self) -> str | None:
        return self._cli_version

    def auth_state(self, owner_id: str) -> str:
        if _resolve_executable(self.executable) is None:
            return "missing"
        return self._auth

    def _invoke(
        self,
        req: LlmRequest,
        route: ResolvedRoute,
        *,
        timeout: float,
        cancel: CancelToken,
        deadline: float,
        key: str | None,
    ) -> ProviderReply:
        call_deadline = min(deadline, time.monotonic() + timeout)
        payload = _stdin_payload(req)
        self._ensure_probe(cancel=cancel, deadline=call_deadline)
        executable = _resolve_executable(self.executable)
        if executable is None:
            raise ProviderError("llm_auth")
        argv = _argv(executable, route)
        try:
            with _private_workdir(self.settings.cache_dir) as cwd:
                cancel.raise_if_set()
                remaining = call_deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderError("llm_timeout")
                budget = min(timeout, remaining)
                result = run(
                    argv,
                    cwd=cwd,
                    env=_child_env(),
                    timeout_s=budget,
                    max_stdout_bytes=MAX_STDOUT_BYTES,
                    max_stderr_bytes=MAX_STDERR_BYTES,
                    cancel=cancel,
                    stdin_data=payload,
                )
        except FileNotFoundError:
            raise ProviderError("llm_auth") from None
        except OSError:
            raise ProviderError("llm_connection") from None
        if result.cancelled:
            cancel.raise_if_set()
            raise ProviderError("llm_timeout")
        if result.timed_out:
            raise ProviderError("llm_timeout")
        check_active(cancel, deadline)
        if result.output_limited or result.stdout_truncated:
            raise ProviderError("llm_invalid_output")
        if result.returncode != 0:
            try:
                payload = _parse_stdout(result.stdout)
            except ProviderError as error:
                if error.code != "llm_invalid_output":
                    raise
                raise ProviderError(
                    _classify_failure("", "", _decode(result.stderr))
                ) from None
            raise ProviderError(
                _classify_failure(
                    _result_text(payload), _subtype(payload), _decode(result.stderr)
                )
            )
        reply = _reply(_parse_stdout(result.stdout), route)
        self._auth = "ok"
        if (
            reply.output_tokens is not None
            and reply.output_tokens > req.max_output_tokens
        ):
            raise ProviderError("llm_invalid_output")
        return reply

    def _ensure_probe(self, *, cancel: CancelToken, deadline: float) -> None:
        if self._probe_ready:
            return
        with self._probe_lock:
            if self._probe_ready:
                return
            executable = _resolve_executable(self.executable)
            if executable is None:
                raise ProviderError("llm_auth")
            version = self._probe(
                [executable, "--version"],
                cancel=cancel,
                deadline=deadline,
                max_stdout_bytes=64 * 1024,
            )
            help_result = self._probe(
                [executable, "--help"],
                cancel=cancel,
                deadline=deadline,
                max_stdout_bytes=1024 * 1024,
            )
            parsed_version = _version(_decode(version.stdout))
            if parsed_version is None or parsed_version < MINIMUM_VERSION:
                raise ProviderError("llm_auth")
            if not _has_required_flags(_decode(help_result.stdout)):
                raise ProviderError("llm_auth")
            self._cli_version = ".".join(str(part) for part in parsed_version)
            self._probe_ready = True

    def _probe(
        self,
        argv: list[str],
        *,
        cancel: CancelToken,
        deadline: float,
        max_stdout_bytes: int,
    ) -> CliProcessResult:
        check_active(cancel, deadline)
        remaining = max(0.001, min(PROBE_TIMEOUT_S, deadline - _now()))
        try:
            with _private_workdir(self.settings.cache_dir) as cwd:
                result = run(
                    argv,
                    cwd=cwd,
                    env=_child_env(),
                    timeout_s=remaining,
                    max_stdout_bytes=max_stdout_bytes,
                    max_stderr_bytes=MAX_STDERR_BYTES,
                    cancel=cancel,
                )
        except OSError:
            raise ProviderError("llm_auth") from None
        if result.cancelled:
            cancel.raise_if_set()
            raise ProviderError("llm_auth")
        if result.timed_out:
            raise ProviderError("llm_timeout")
        if (
            result.returncode != 0
            or result.output_limited
            or result.stdout_truncated
        ):
            raise ProviderError("llm_auth")
        return result


def create(
    settings: AppSettings, *, credentials: CredentialResolver | None = None
) -> ClaudeCliLlm:
    return ClaudeCliLlm(settings)


def _now() -> float:
    return time.monotonic()


def _resolve_executable(value: str) -> str | None:
    found = shutil.which(value)
    return found if found else None


def _child_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for name, value in os.environ.items():
        if name not in ENV_ALLOWLIST:
            continue
        upper = name.upper()
        if any(marker in upper for marker in SECRET_ENV_MARKERS):
            continue
        env[name] = value
    return env


@contextmanager
def _private_workdir(cache_dir: Path | str) -> Iterator[Path]:
    base = Path(cache_dir) / "llm"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        pass
    root = base / PROVIDER
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=root))
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _argv(executable: str, route: ResolvedRoute) -> list[str]:
    return [
        executable,
        "--print",
        "--safe-mode",
        "--restricted",
        "--tools",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--permission-prompts",
        "none",
        "--output-format",
        "stream-json",
        "--input-format",
        "stream-json",
        "--verbose",
        "--effort",
        route.effort,
        "--model",
        route.model,
    ]


def _stdin_payload(req: LlmRequest) -> bytes:
    content: list[dict[str, Any]] = [{"type": "text", "text": req.system}]
    constraints = [f"Keep the response within {req.max_output_tokens} output tokens."]
    if req.output_schema is not None:
        constraints.append(schema_instruction(req.output_schema))
    content.append({"type": "text", "text": "\n".join(constraints)})
    for part in req.parts:
        if part.kind == "png":
            if not part.png:
                # Frames are the only image data (CONTRACTS 10.1).
                raise ProviderError("llm_refused")
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(part.png).decode("ascii"),
                    },
                }
            )
        elif part.kind == "text":
            content.append({"type": "text", "text": part.text or ""})
        else:
            raise ProviderError("llm_refused")
    message = {"type": "user", "message": {"role": "user", "content": content}}
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def _parse_stdout(raw: bytes) -> dict[str, Any]:
    """Read the stream-json event lines and return the final result event.

    Every event is checked for tool activity, not only the result, because tool
    calls appear in intermediate assistant and user events.
    """
    text = _decode(raw).strip()
    if not text:
        raise ProviderError("llm_invalid_output")
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            raise ProviderError("llm_invalid_output") from None
        if not isinstance(event, dict):
            raise ProviderError("llm_invalid_output")
        events.append(event)
    results = [event for event in events if event.get("type") == "result"]
    if not results:
        raise ProviderError("llm_invalid_output")
    payload = results[-1]
    if _is_error(payload):
        raise ProviderError(
            _classify_failure(_result_text(payload), _subtype(payload), "")
        )
    if any(_has_tool_activity(event) for event in events):
        raise ProviderError("llm_invalid_output")
    return payload


def _is_error(payload: Mapping[str, Any]) -> bool:
    if payload.get("is_error") is True:
        return True
    subtype = payload.get("subtype")
    if isinstance(subtype, str):
        lowered = subtype.casefold()
        if lowered.startswith("error") or lowered in {"failure", "failed", "refusal"}:
            return True
    return payload.get("type") == "error"


def _subtype(payload: Mapping[str, Any]) -> str:
    value = payload.get("subtype")
    return value.casefold() if isinstance(value, str) else ""


def _result_text(payload: Mapping[str, Any]) -> str:
    for key in ("result", "error"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                continue
    return ""


def _classify_failure(text: str, subtype: str, stderr: str) -> str:
    haystack = f" {subtype} {text} {stderr} ".casefold()
    if "max_budget" in subtype:
        return "llm_quota"
    if any(marker in haystack for marker in QUOTA_MARKERS):
        return "llm_quota"
    if subtype and any(marker in subtype for marker in ("auth", "login", "credential")):
        return "llm_auth"
    if any(marker in haystack for marker in AUTH_MARKERS):
        return "llm_auth"
    if any(marker in haystack for marker in RATE_MARKERS):
        return "llm_rate_limited"
    if any(marker in haystack for marker in TIMEOUT_MARKERS):
        return "llm_timeout"
    if "max_turns" in subtype:
        return "llm_refused"
    if "tool" in subtype:
        return "llm_invalid_output"
    if any(marker in haystack for marker in REFUSAL_MARKERS):
        return "llm_refused"
    if any(marker in haystack for marker in INVALID_MARKERS):
        return "llm_invalid_output"
    if any(marker in haystack for marker in CONNECTION_MARKERS):
        return "llm_connection"
    if any(marker in haystack for marker in USAGE_MARKERS):
        return "llm_invalid_output"
    return "llm_connection"


def _has_tool_activity(value: Any) -> bool:
    if isinstance(value, Mapping):
        kind = value.get("type")
        if isinstance(kind, str) and kind.casefold() in TOOL_ACTIVITY_TYPES:
            return True
        for key in ("tool_use", "tool_result", "tool_uses"):
            if value.get(key):
                return True
        return any(_has_tool_activity(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_tool_activity(item) for item in value)
    return False


def _reply(payload: Mapping[str, Any], route: ResolvedRoute) -> ProviderReply:
    text = _output_text(payload)
    if text is None:
        raise ProviderError("llm_invalid_output")
    model = _actual_model(payload, route.model)
    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens = _usage(payload)
    return ProviderReply(
        text=text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )


def _output_text(payload: Mapping[str, Any]) -> str | None:
    structured = payload.get("structured_output")
    if structured is not None:
        if isinstance(structured, Mapping):
            return json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
        if isinstance(structured, str):
            return structured
        raise ProviderError("llm_invalid_output")
    result = payload.get("result")
    if isinstance(result, str):
        return result
    if isinstance(result, Mapping):
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if isinstance(result, list):
        chunks: list[str] = []
        for block in result:
            if isinstance(block, Mapping) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            elif isinstance(block, str):
                chunks.append(block)
        if chunks:
            return "\n".join(chunks)
    return None


def _actual_model(payload: Mapping[str, Any], fallback: str) -> str:
    usage = payload.get("modelUsage")
    models: list[str] = []
    if isinstance(usage, Mapping):
        models = [key for key in usage if isinstance(key, str)]
        if payload.get("model") in models:
            models = [payload["model"]]
        elif len(models) > 1:
            models.sort(key=lambda key: (-_model_output_tokens(usage.get(key)), key))
            models = models[:1]
    if not models and isinstance(payload.get("model"), str):
        models = [payload["model"]]
    if not models:
        models = [fallback]
    model = models[0]
    return model if 0 < len(model) <= 80 else fallback


def _model_output_tokens(entry: Any) -> int:
    if not isinstance(entry, Mapping):
        return 0
    value = token_count(entry.get("output_tokens", entry.get("outputTokens")))
    return value if value is not None else 0


def _usage(payload: Mapping[str, Any]) -> tuple[int | None, int | None, int | None, int | None]:
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        direct = (
            _token(usage, ("input_tokens", "inputTokens")),
            _token(usage, ("output_tokens", "outputTokens")),
            _token(usage, ("cache_read_input_tokens", "cacheReadInputTokens")),
            _token(usage, ("cache_creation_input_tokens", "cacheCreationInputTokens")),
        )
        if all(value is not None for value in direct):
            return direct
    else:
        direct = (None, None, None, None)
    model_usage = payload.get("modelUsage")
    if not isinstance(model_usage, Mapping):
        return direct
    entries = [entry for entry in model_usage.values() if isinstance(entry, Mapping)]
    totals: list[int | None] = []
    for snake, camel_name, present in zip(
        (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ),
        (
            "inputTokens",
            "outputTokens",
            "cacheReadInputTokens",
            "cacheCreationInputTokens",
        ),
        direct,
        strict=True,
    ):
        if present is not None:
            totals.append(present)
            continue
        total: int | None = None
        for entry in entries:
            value = token_count(entry.get(snake, entry.get(camel_name)))
            if value is not None:
                total = value if total is None else total + value
        totals.append(total)
    return totals[0], totals[1], totals[2], totals[3]


def _token(usage: Mapping[str, Any], names: tuple[str, str]) -> int | None:
    for name in names:
        value = token_count(usage.get(name))
        if value is not None:
            return value
    return None


def _version(text: str) -> tuple[int, int, int] | None:
    match = VERSION_PATTERN.search(text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _has_required_flags(help_text: str) -> bool:
    present: set[str] = set()
    clean = re.sub("\\x1b\\[[0-9;]*[A-Za-z]", "", help_text)
    for line in clean.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("-"):
            continue
        head = stripped.split("  ", 1)[0]
        present.update(re.findall(r"--[a-z][a-z0-9-]*", head))
    return all(flag in present for flag in REQUIRED_FLAGS)
