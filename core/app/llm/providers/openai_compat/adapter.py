"""Standard Chat Completions transport; no account or OAuth discovery."""

from __future__ import annotations

import base64
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.llm.common import (
    BaseLlm,
    ProviderError,
    ProviderReply,
    ResolvedRoute,
    settings_options,
    status_error,
    token_count,
)
from app.llm.schema_prompt import schema_instruction
from app.ports import AppSettings, CancelToken, CredentialResolver, LlmRequest

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenAiCompatLlm(BaseLlm):
    provider = "openai_compat"

    def __init__(self, settings: AppSettings, *, routing: Any = None,
                 base_url: str | None = None, credentials: CredentialResolver | None = None,
                 key_required: bool = False, key_env: str | None = None,
                 opener: Any = None) -> None:
        super().__init__(settings, routing=routing, credentials=credentials)
        options = settings_options(settings, self.provider)
        base_url = base_url or options.get("base_url") or os.environ.get("APP_LLM_BASE_URL")
        if not base_url:
            raise ValueError("OpenAI-compatible base_url is required")
        url = urllib.parse.urlsplit(base_url)
        if (url.scheme not in ("https", "http") or not url.hostname
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("OpenAI-compatible base_url must be an HTTP endpoint")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.key_env = key_env or options.get("key_env")
        self.requires_key = bool(key_required or options.get("key_required", False))
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
        )

    def _developer_key(self) -> str | None:
        return None if not self.key_env else os.environ.get(self.key_env)

    def _invoke(self, req: LlmRequest, route: ResolvedRoute, *, timeout: float,
                cancel: CancelToken, deadline: float, key: str | None) -> ProviderReply:
        if self.requires_key and not key:
            raise ProviderError("llm_auth")
        payload = _request_payload(req, route)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(
            self.url, json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProviderError("llm_invalid_output")
            data = json.loads(raw)
        except urllib.error.HTTPError as error:
            try:
                body = json.loads(error.read(65536))
                code = body.get("error", {}).get("code")
            except (ValueError, AttributeError, TypeError):
                code = None
            finally:
                error.close()
            raise status_error(
                error.code, quota=code in ("insufficient_quota", "quota_exceeded"),
                image=any(part.kind == "png" for part in req.parts),
                retry_after=error.headers.get("Retry-After"),
            ) from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("llm_timeout") from None
        except urllib.error.URLError as error:
            code = "llm_timeout" if isinstance(error.reason, TimeoutError) else "llm_connection"
            raise ProviderError(code) from None
        except OSError:
            raise ProviderError("llm_connection") from None
        except ValueError:
            raise ProviderError("llm_invalid_output") from None
        return _reply(data, route)


def _request_payload(req: LlmRequest, route: ResolvedRoute) -> dict[str, Any]:
    parts = []
    for part in req.parts:
        if part.kind == "png" and part.png is not None:
            encoded = base64.b64encode(part.png).decode("ascii")
            parts.append({"type": "image_url", "image_url": {
                "url": f"data:image/png;base64,{encoded}"
            }})
        elif part.kind == "text" and part.text is not None:
            parts.append({"type": "text", "text": part.text})
        else:
            raise ProviderError("llm_invalid_output")
    system = req.system
    if req.output_schema is not None:
        system += "\n\n" + schema_instruction(req.output_schema)
    payload = {
        "model": route.model, "reasoning_effort": route.effort,
        "max_tokens": req.max_output_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": parts}],
    }
    if req.output_schema is not None:
        payload["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "response", "strict": True, "schema": req.output_schema,
        }}
    return payload


def _reply(data: Any, route: ResolvedRoute) -> ProviderReply:
    try:
        choice = data["choices"][0]
        message = choice["message"]
        if (message.get("refusal") or message.get("tool_calls")
                or choice.get("finish_reason") == "content_filter"):
            raise ProviderError("llm_refused")
        text = message["content"]
        model = data.get("model", route.model)
        usage = data.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        if not isinstance(text, str) or not isinstance(model, str):
            raise TypeError
        prompt_tokens = token_count(usage.get("prompt_tokens"))
        cached_tokens = token_count(details.get("cached_tokens"))
        if prompt_tokens is None:
            input_tokens = None
        elif cached_tokens is None:
            input_tokens = prompt_tokens
        else:
            input_tokens = prompt_tokens - cached_tokens
        return ProviderReply(
            text, model, input_tokens,
            token_count(usage.get("completion_tokens")), cached_tokens,
            token_count(usage.get("cache_write_tokens")),
        )
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ProviderError("llm_invalid_output") from None


def create(
    settings: AppSettings, *, credentials: CredentialResolver | None = None
) -> OpenAiCompatLlm:
    return OpenAiCompatLlm(settings, credentials=credentials)
