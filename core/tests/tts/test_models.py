"""Real synthesis with the prepared model files: `pytest -m models`.

Needs the output of `scripts/dev_setup.py --models` under APP_MODEL_DIR. The adapter
runs with its contract timeouts; a slow host must report the measured limit rather
than silently extending the deadline.

Each language runs the production generate path with the real voice service and the
real engine for the tts and align stages, so the second run shows the pipeline cache.
"""

from __future__ import annotations

import dataclasses
import wave
from pathlib import Path
from typing import Any

import pytest

from app.ports import SynthResult
from app.schemas.artifact import AlignFallback, Timing
from app.schemas.common import CaptionMode, Language
from app.schemas.job import JobKind
from app.services.pipeline.build import run_generate
from app.services.pipeline.cache_keys import Graph
from app.services.pipeline.types import KeyRuntime
from app.services.voice.service import VoiceService
from app.settings import Settings
from app.tools.align.adapter import UnavailableAligner
from app.tools.tts.qwen3_tts_0_6b.adapter import (
    SAMPLE_RATE,
    Qwen3TtsAdapter,
    create,
)
from tests.pipeline.support import Harness, build_harness

pytestmark = pytest.mark.models

LINES = {
    "ko": (
        ("커피는 세 가지다.", "커피는 세 가지다."),
        ("가격은 12,500원.", "가격은 만 이천오백 원."),
    ),
    "en": (
        ("Coffee has three parts.", "Coffee has three parts."),
        ("It costs $12.50.", "It costs twelve dollars fifty."),
    ),
}
VOICES = {"ko": "sohee_ko", "en": "ryan_en"}


class CountingTts:
    """The real engine behind a call counter."""

    def __init__(self, inner: Qwen3TtsAdapter) -> None:
        self.inner = inner
        self.calls: list[str] = []
        self.results: list[SynthResult] = []

    def info(self):  # type: ignore[no-untyped-def]
        return self.inner.info()

    def ready(self) -> list[str]:
        return self.inner.ready()

    def synthesize(self, text, language, voice, *, out_dir, cancel):  # type: ignore[no-untyped-def]
        self.calls.append(text)
        result = self.inner.synthesize(text, language, voice, out_dir=out_dir, cancel=cancel)
        self.results.append(result)
        return result

    def close(self) -> None:
        self.inner.close()


@pytest.fixture(scope="module")
def engine():  # type: ignore[no-untyped-def]
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("APP_PROFILE", "dev")
        patch.setenv("APP_DEPLOYMENT", "local")
        adapter = create(Settings())
    missing = adapter.ready()
    if missing:
        pytest.fail(f"run scripts/dev_setup.py --models first; not prepared: {missing}")
    yield adapter
    adapter.close()


def _video(harness: Harness, language: str) -> Any:
    base = harness.new_video()
    first, second = base.scene_order[:2]
    scenes = {}
    for scene_id, (display, speech) in zip((first, second), LINES[language], strict=True):
        scene = base.scenes[scene_id]
        line = scene.lines[0].model_copy(update={"display_text": display, "speech_text": speech})
        scenes[scene_id] = scene.model_copy(update={"lines": [line]})
    audio = base.settings.audio.model_copy(
        update={"voice": harness.catalog.pin("voice", VOICES[language])}
    )
    settings = base.settings.model_copy(
        update={
            "language": Language(language),
            "audio": audio,
            "caption": base.settings.caption.model_copy(update={"mode": CaptionMode.phrase}),
        }
    )
    return harness.revise(
        base, settings=settings, scenes=scenes, scene_order=[first, second]
    )


def _generate(harness: Harness, video: Any, services: Any) -> None:
    job = harness.job(JobKind.generate, video=video)
    ctx = harness.context(job, deadline_seconds=3 * 3600)
    run_generate(job, ctx, services)


@pytest.fixture(scope="module", params=["ko", "en"])
def generated(request, engine, tmp_path_factory):  # type: ignore[no-untyped-def]
    language = request.param
    harness = build_harness(tmp_path_factory.mktemp(f"pipeline_{language}"))
    try:
        counting = CountingTts(engine)
        voice = VoiceService(counting, UnavailableAligner(), harness.artifacts)  # type: ignore[arg-type]
        services = dataclasses.replace(
            harness.services,
            voice=voice,
            key_runtime=KeyRuntime(
                sandbox_digest="sandbox-test",
                aligner_digest=None,
                renderer_revision="renderer-test",
                encoder_digest="encoder-test",
            ),
        )
        video = _video(harness, language)
        _generate(harness, video, services)
        first_calls = list(counting.calls)
        _generate(harness, video, services)
        graph = Graph(video, services)
        timings = {}
        for scene_id in video.scene_order:
            artifact = harness.artifacts.find(video.owner_id, graph.scenes[scene_id].timing)
            assert artifact is not None
            timings[scene_id] = Timing.model_validate_json(
                harness.artifacts.path(artifact.id).read_text(encoding="utf-8")
            )
        yield {
            "language": language,
            "video": video,
            "first_calls": first_calls,
            "all_calls": list(counting.calls),
            "timings": timings,
            "results": list(counting.results),
            "artifacts": harness.artifacts,
        }
    finally:
        harness.close()


def _frames(path: Path) -> tuple[int, int, int, int]:
    with wave.open(str(path), "rb") as handle:
        return (
            handle.getnchannels(),
            handle.getsampwidth(),
            handle.getframerate(),
            handle.getnframes(),
        )


def test_11_15_28_models_measure_two_lines_and_reuse_the_pipeline_cache(
    generated,  # type: ignore[no-untyped-def]
) -> None:
    speech = [speech for _, speech in LINES[generated["language"]]]
    assert generated["first_calls"] == speech
    assert generated["all_calls"] == speech
    assert len(generated["results"]) == 2
    video = generated["video"]
    for scene_id, result in zip(video.scene_order, generated["results"], strict=True):
        timed = generated["timings"][scene_id].lines[0]
        channels, width, rate, frames = _frames(generated["artifacts"].path(timed.tts.id))
        assert (channels, width, rate) == (1, 2, SAMPLE_RATE)
        assert result.duration_ms == frames * 1000 // rate
        assert 500 <= result.duration_ms <= 20000
        assert timed.speech_ms == result.duration_ms
        assert timed.caption.mode_used is CaptionMode.sentence
        assert timed.caption.fallback_reason is AlignFallback.align_unavailable
        assert timed.caption.phrases == []
    second = video.scenes[video.scene_order[1]].lines[0]
    assert second.display_text != second.speech_text
