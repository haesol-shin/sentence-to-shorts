"""Opt-in acceptance; ordinary test runs never call a live endpoint.

Select with APP_PROFILE=dev pytest tests/llm -m realllm -q. Supply
APP_LLM_BASE_URL, alias model IDs in models.yaml (or APP_LLM_MODEL_HAIKU and
APP_LLM_MODEL_SONNET), and optionally APP_LLM_KEY_ENV naming the key variable.
The integration environment supplies these values, not recorded test fixtures.
"""

from __future__ import annotations

import io
import os
import threading
import time

import pytest
from PIL import Image

from app.llm.client import LlmClient
from app.ports import AppError, Cancelled, LlmPart, LlmRequest, LlmTask
from app.settings import Settings

pytestmark = pytest.mark.realllm


class _Cancel:
    def __init__(self):
        self.event = threading.Event()

    def is_set(self):
        return self.event.is_set()

    def raise_if_set(self):
        if self.event.is_set():
            raise Cancelled()

    def wait(self, seconds):
        return self.event.wait(seconds)


@pytest.fixture
def real_client(request):
    if request.config.getoption("markexpr").strip() != "realllm":
        pytest.skip("live calls require explicit -m realllm selection")
    settings = Settings()
    assert settings.profile == "dev", "live acceptance requires the dev profile"
    routing = settings.models.model_copy(deep=True)
    for alias in ("haiku", "sonnet"):
        model = os.environ.get(f"APP_LLM_MODEL_{alias.upper()}")
        if model:
            routing.models[alias]["openai_compat"] = model
    endpoint = os.environ.get("APP_LLM_BASE_URL")
    assert endpoint, "APP_LLM_BASE_URL must be configured for live acceptance"
    return LlmClient(settings, routing=routing, options={
        "base_url": endpoint, "key_env": os.environ.get("APP_LLM_KEY_ENV"),
    })


def _request(task, parts):
    return LlmRequest(
        task, task.value, "Return a JSON object with an answer string.", parts,
        {"type": "object", "properties": {"answer": {"type": "string"}},
         "required": ["answer"], "additionalProperties": False}, 128,
    )


def test_10_real_structured_request_and_usage(real_client, record_property):
    result = real_client.complete(
        _request(LlmTask.draft, [LlmPart("text", text="Say hello briefly in Korean.")]),
        cancel=_Cancel(), deadline=time.monotonic() + 180,
    )
    assert isinstance(result.parsed["answer"], str)
    assert result.usage.input_tokens is not None
    assert result.usage.output_tokens is not None
    record_property("usage", result.usage.model_dump(mode="json"))
    print(result.usage.model_dump_json())


def test_10_real_image_is_supported_or_explicitly_refused(real_client, record_property):
    image = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(image, format="PNG")
    try:
        result = real_client.complete(
            _request(LlmTask.reference_vision, [LlmPart("text", text="Name the image color."),
                                                LlmPart("png", png=image.getvalue())]),
            cancel=_Cancel(), deadline=time.monotonic() + 180,
        )
    except AppError as error:
        assert error.code == "llm_refused"
        record_property("image_result", "llm_refused")
        print("reference_vision: llm_refused")
    else:
        assert isinstance(result.parsed["answer"], str)
        record_property("image_result", "supported")
        record_property("usage", result.usage.model_dump(mode="json"))
        print(result.usage.model_dump_json())
