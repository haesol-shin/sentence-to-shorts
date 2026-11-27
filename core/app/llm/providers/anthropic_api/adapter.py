"""Official Anthropic SDK, isolated from provider-neutral modules."""

from __future__ import annotations

import base64
import logging
from typing import Any

import anthropic

from app.llm.common import (
    BaseLlm,
    ProviderError,
    ProviderReply,
    ResolvedRoute,
    settings_options,
    status_error,
    token_count,
)
from app.ports import AppSettings, CancelToken, CredentialResolver, LlmRequest


class _NoSdkPayloadLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


# The SDK logs request bodies and exception details at DEBUG. Usage is returned
# through the port instead; third-party diagnostics must not bypass log policy.
_privacy_filter = _NoSdkPayloadLogs()
for _name, _logger in list(logging.Logger.manager.loggerDict.items()):
    if _name.startswith(("anthropic", "httpx2")) and isinstance(_logger, logging.Logger):
        _logger.addFilter(_privacy_filter)


class AnthropicApiLlm(BaseLlm):
    provider = "anthropic_api"
    requires_key = True

    def __init__(self, settings: AppSettings, *, routing: Any = None,
                 credentials: CredentialResolver | None = None,
                 http_transport: Any = None) -> None:
        super().__init__(settings, routing=routing, credentials=credentials)
        self.http_transport = http_transport
        self.base_url = settings_options(settings, self.provider).get(
            "base_url", "https://api.anthropic.com"
        )

    def _invoke(self, req: LlmRequest, route: ResolvedRoute, *, timeout: float,
                cancel: CancelToken, deadline: float, key: str | None) -> ProviderReply:
        if not key:
            raise ProviderError("llm_auth")
        parts = []
        for part in req.parts:
            if part.kind == "png" and part.png is not None:
                parts.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(part.png).decode("ascii"),
                }})
            elif part.kind == "text" and part.text is not None:
                parts.append({"type": "text", "text": part.text})
            else:
                raise ProviderError("llm_invalid_output")
        system = [{"type": "text", "text": req.system}]
        # Scene data sends video-wide context first, then the individual scene.
        breakpoint = system[0]
        if req.route == "scene_data" and len(parts) >= 2:
            breakpoint = parts[0]
        breakpoint["cache_control"] = {"type": "ephemeral"}
        output: dict[str, Any] = {"effort": route.effort}
        if req.output_schema is not None:
            output["format"] = {
                "type": "json_schema", "schema": anthropic.transform_schema(req.output_schema),
            }
        try:
            with anthropic.Anthropic(
                api_key=key, base_url=self.base_url, max_retries=0, timeout=timeout,
                open_telemetry=False,
                default_headers={"authorization": anthropic.omit, "x-api-key": key},
                http_client=anthropic.DefaultHttpxClient(
                    trust_env=False, follow_redirects=False, transport=self.http_transport
                ),
            ) as client:
                message = client.messages.create(
                    model=route.model, system=system, max_tokens=req.max_output_tokens,
                    output_config=output, messages=[{"role": "user", "content": parts}],
                )
        except anthropic.APITimeoutError:
            raise ProviderError("llm_timeout") from None
        except anthropic.APIConnectionError:
            raise ProviderError("llm_connection") from None
        except anthropic.APIStatusError as error:
            body = error.body if isinstance(error.body, dict) else {}
            kind = body.get("error", body)
            kind = kind.get("type") if isinstance(kind, dict) else None
            raise status_error(
                error.status_code,
                quota=kind in ("insufficient_quota", "quota_exceeded", "billing_error",
                               "enforced_spend_limit_reached"),
                retry_after=error.response.headers.get("retry-after"),
            ) from None
        except anthropic.APIError:
            raise ProviderError("llm_invalid_output") from None
        return _reply(message)


def _reply(message: Any) -> ProviderReply:
    try:
        if message.stop_reason == "refusal" or any(
            block.type != "text" for block in message.content
        ):
            raise ProviderError("llm_refused")
        text = "".join(block.text for block in message.content)
        if not text or not isinstance(message.model, str):
            raise ProviderError("llm_invalid_output")
        usage = message.usage
        return ProviderReply(
            text, message.model, token_count(usage.input_tokens),
            token_count(usage.output_tokens),
            token_count(getattr(usage, "cache_read_input_tokens", None)),
            token_count(getattr(usage, "cache_creation_input_tokens", None)),
        )
    except (TypeError, AttributeError):
        raise ProviderError("llm_invalid_output") from None


def create(
    settings: AppSettings, *, credentials: CredentialResolver | None = None
) -> AnthropicApiLlm:
    return AnthropicApiLlm(settings, credentials=credentials)
