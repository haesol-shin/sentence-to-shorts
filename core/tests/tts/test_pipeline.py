"""Speech cache and caption fallback through the production pipeline, without models.

Reuse the model acceptance scenarios with a subprocess fake instead of the large
model. This proves cache behavior, not synthesis quality or model readiness.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.tts.support import make_adapter
from tests.tts.test_models import generated as generated
from tests.tts.test_models import (
    test_11_15_28_models_measure_two_lines_and_reuse_the_pipeline_cache as _assert_pipeline_result,
)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):  # type: ignore[no-untyped-def]
    lock = Path(__file__).resolve().parents[2] / "config" / "runtime.lock.json"
    model = next(
        item for item in json.loads(lock.read_text(encoding="utf-8"))["items"]
        if item["id"] == "model-tts-qwen3-0.6b"
    )
    adapter = make_adapter(
        tmp_path_factory.mktemp("pipeline_worker"), model_revision=model["revision"]
    )
    try:
        yield adapter
    finally:
        adapter.close()


def test_11_15_cache_hit_keeps_the_published_wav_and_caption_reason(
    generated,  # type: ignore[no-untyped-def]
) -> None:
    _assert_pipeline_result(generated)
