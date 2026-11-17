"""Provider-neutral routing, retry budgets and output validation."""

from __future__ import annotations

import json
import math
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, replace
from email.utils import parsedate_to_datetime
from typing import Any

from jsonschema import SchemaError
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import Unresolvable

from app.ports import (
    AppError,
    AppSettings,
    CancelToken,
    CredentialResolver,
    LlmPart,
    LlmRequest,
    LlmResult,
)
from app.schemas.job import Stage, Usage

STAGES = {
    "draft": Stage.llm_draft, "script": Stage.llm_script, "split": Stage.llm_split,
    "scene_data": Stage.llm_scene_data, "chat": Stage.llm_chat,
    "scene_rewrite": Stage.llm_chat, "precheck": Stage.llm_precheck,
    "reference_vision": Stage.ref_llm, "style_code": Stage.code_llm,
    "template_code": Stage.code_llm, "bgm_code": Stage.code_llm,
}


@dataclass(frozen=True)
class ResolvedRoute:
    model: str
    effort: str
    timeout_s: float
    retries: int


@dataclass(frozen=True)
class ProviderReply:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None


class ProviderError(AppError):
    def __init__(self, code: str, *, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.retry_after = retry_after


def retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def status_error(status: int, *, quota: bool = False, image: bool = False,
                 retry_after: str | None = None) -> ProviderError:
    if status in (401, 403):
        code = "llm_auth"
    elif quota:
        code = "llm_quota"
    elif status == 429:
        code = "llm_rate_limited"
    elif status == 402:
        code = "llm_quota"
    elif status == 408:
        code = "llm_timeout"
    elif status >= 500:
        code = "llm_connection"
    elif image or status in (400, 404, 413, 422):
        code = "llm_refused"
    else:
        code = "llm_invalid_output"
    return ProviderError(code, retry_after=retry_after_seconds(retry_after))


def check_active(cancel: CancelToken, deadline: float) -> float:
    cancel.raise_if_set()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AppError("deadline_exceeded")
    return remaining


def wait_active(seconds: float, *, cancel: CancelToken, deadline: float) -> None:
    until = time.monotonic() + seconds
    while True:
        remaining = check_active(cancel, deadline)
        delay = min(0.25, until - time.monotonic(), remaining)
        if delay <= 0:
            return
        cancel.wait(delay)


def validate_output(text: str, schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if schema is None:
        return None
    try:
        parsed = json.loads(text)
        validator = validator_for(schema)
        validator.check_schema(schema)
        validator(schema, registry=Registry()).validate(parsed)
        if not isinstance(parsed, dict):
            raise ValueError("object required")
        return parsed
    except (ValueError, SchemaError, ValidationError, Unresolvable) as error:
        # Never include the failing value or provider text in an exception.
        rule = error.validator if isinstance(error, ValidationError) else "json_object"
        raise AppError("llm_invalid_output", detail={"validation_rule": rule}) from None


def resolve_route(routing: Any, route_id: str, provider: str) -> ResolvedRoute:
    try:
        route = routing.routes[route_id]
        model = routing.models[route.model][provider]
        if not model:
            raise KeyError("empty model")
        return ResolvedRoute(model, route.effort, route.timeout_s, route.retries)
    except (KeyError, AttributeError):
        raise AppError("llm_invalid_output", detail={"configuration": "route"}) from None


def token_count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _add_known(old: int | None, new: int | None) -> int | None:
    return None if old is None or new is None else old + new


class BaseLlm(ABC):
    provider: str
    requires_key = False

    def __init__(
        self,
        settings: AppSettings,
        *,
        routing: Any = None,
        credentials: CredentialResolver | None = None,
    ) -> None:
        self.settings = settings
        self.routing = routing if routing is not None else settings.models
        self.credentials = credentials
        self._auth = "unknown"
        self._failed: dict[str, str | None] = {}
        self._ok: dict[str, str | None] = {}

    def _developer_key(self) -> str | None:
        """A developer environment key, when the bootstrap configured one."""
        return None

    def _available(self, owner_id: str) -> bool:
        return True

    def _slot(self, owner_id: str) -> str | None:
        """What names the key currently in effect: `env` or a credential id."""
        if self._developer_key() is not None:
            return "env"
        if self.credentials is None:
            return None
        return self.credentials.credential_id(owner_id, self.provider)

    def _resolve(self, owner_id: str) -> tuple[str | None, str | None]:
        """Resolve the key once at the start of a call: (slot, secret)."""
        developer = self._developer_key()
        if developer is not None:
            return "env", developer
        if self.credentials is None:
            return None, None
        resolved = self.credentials.resolve(owner_id, self.provider)
        if resolved is None:
            return None, None
        return resolved.credential_id, resolved.secret

    def auth_state(self, owner_id: str) -> str:
        if not self._available(owner_id):
            return "missing"
        slot = self._slot(owner_id)
        if slot is None:
            if self.requires_key:
                return "missing"
            if owner_id in self._failed and self._failed[owner_id] is None:
                return "expired"
            if owner_id in self._ok and self._ok[owner_id] is None:
                return "ok"
            return "unknown"
        if self._failed.get(owner_id) == slot:
            return "expired"
        return "ok" if self._ok.get(owner_id) == slot else "unknown"

    @abstractmethod
    def _invoke(self, req: LlmRequest, route: ResolvedRoute, *, timeout: float,
                cancel: CancelToken, deadline: float,
                key: str | None) -> ProviderReply:
        """Issue one attempt without changing the selected route."""

    def complete(
        self, req: LlmRequest, *, owner_id: str, cancel: CancelToken, deadline: float
    ) -> LlmResult:
        started = time.monotonic()
        check_active(cancel, deadline)
        slot, key = self._resolve(owner_id)
        if self.requires_key and key is None:
            self._failed[owner_id] = slot
            raise AppError("llm_auth")
        route = resolve_route(self.routing, req.route, self.provider)
        if sum(part.kind == "png" for part in req.parts) > 8:
            raise AppError("llm_refused")
        counts: dict[str, int | None] = dict.fromkeys(
            ("input_tokens", "output_tokens", "cache_read_tokens"), 0
        )
        failures: dict[str, int] = {}
        calls = 0
        repaired = False
        current = req
        while True:
            timeout = min(route.timeout_s, check_active(cancel, deadline))
            try:
                calls += 1
                reply = self._invoke(current, route, timeout=timeout,
                                     cancel=cancel, deadline=deadline, key=key)
            except ProviderError as error:
                check_active(cancel, deadline)
                if error.code == "llm_auth":
                    self._failed[owner_id] = slot
                    self._auth = "expired" if self._auth == "ok" else "missing"
                cap = {"llm_timeout": 1, "llm_connection": 2, "llm_rate_limited": 2}.get(
                    error.code, 0
                )
                used = failures.get(error.code, 0)
                # A mixed sequence cannot escape the configured retry budget.
                if used >= cap or sum(failures.values()) >= min(route.retries, 2):
                    raise AppError(error.code) from None
                failures[error.code] = used + 1
                delay = error.retry_after
                wait_active(delay if delay is not None else 2.0 ** used,
                            cancel=cancel, deadline=deadline)
                continue
            check_active(cancel, deadline)
            self._auth = "ok"
            self._ok[owner_id] = slot
            for name in counts:
                counts[name] = _add_known(counts[name], getattr(reply, name))
            try:
                parsed = validate_output(reply.text, req.output_schema)
            except AppError as error:
                if repaired:
                    raise
                repaired = True
                rule = error.detail.get("validation_rule", "json_object")
                repair = LlmPart(
                    kind="text",
                    text="Return a corrected JSON object matching the output schema. "
                         f"Validation error: {rule}. Previous output:\n{reply.text}",
                )
                current = replace(req, parts=[*req.parts, repair])
                continue
            check_active(cancel, deadline)
            return LlmResult(reply.text, parsed, Usage(
                stage=STAGES[req.task.value], provider=self.provider, model=reply.model,
                effort=route.effort, input_tokens=counts["input_tokens"],
                output_tokens=counts["output_tokens"],
                cache_read_tokens=counts["cache_read_tokens"],
                cost_usd=None, wall_ms=max(0, int((time.monotonic() - started) * 1000)),
                retries=calls - 1,
            ))


def settings_options(settings: AppSettings, provider: str) -> Mapping[str, Any]:
    """Optional provider settings injected by the composition root, not user data."""
    return getattr(settings, "llm_options", {}).get(provider, {})
