"""The aligner app.yaml selects reports `align_unavailable` and never invents a time."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.jobs import CancelFlag
from app.ports import Cancelled
from app.schemas.artifact import AlignFallback
from app.schemas.common import CaptionMode
from app.services.voice.service import VoiceService
from app.settings import Settings
from app.tools.align.adapter import UnavailableAligner, create
from app.tools.tts.fixed_wav.adapter import FixedWavTts
from tests.voice.test_service import (
    VOICE_PIN,
    FakeArtifactStore,
    make_ctx,
    make_line,
    make_scene,
    publish,
)


@pytest.fixture
def none_settings(app_settings: Settings) -> Settings:
    app_settings.providers.adapters["aligner"] = "none"
    return app_settings


def test_15_selected_none_reports_align_unavailable(
    none_settings: Settings, tmp_path: Path
) -> None:
    aligner = create(none_settings)
    assert isinstance(aligner, UnavailableAligner)
    result = aligner.align(
        tmp_path / "missing.wav", "에이 원", "A1", "ko", cancel=CancelFlag()
    )
    assert (result.phrases, result.failure) == (None, "align_unavailable")


def test_15_unavailable_aligner_stops_on_cancel(none_settings: Settings, tmp_path: Path) -> None:
    cancel = CancelFlag()
    cancel.cancel()
    with pytest.raises(Cancelled):
        create(none_settings).align(tmp_path / "x.wav", "a", "a", "en", cancel=cancel)


@pytest.mark.parametrize("selected", ["default", "whisperx"])
def test_15_no_other_aligner_is_implemented(app_settings: Settings, selected: str) -> None:
    app_settings.providers.adapters["aligner"] = selected
    with pytest.raises(NotImplementedError):
        create(app_settings)


@pytest.mark.parametrize(
    ("language", "display", "speech"),
    [
        ("ko", "가격 12,500원", "가격 만 이천오백 원"),
        ("en", "CPU costs $12.50", "C P U costs twelve dollars"),
    ],
)
def test_15_voice_service_turns_the_line_into_a_sentence_caption_with_the_reason(
    tmp_path: Path, none_settings: Settings, language: str, display: str, speech: str
) -> None:
    store = FakeArtifactStore()
    service = VoiceService(FixedWavTts(), create(none_settings), store)
    ctx = make_ctx(tmp_path)
    line = make_line(0, display, speech)
    refs = publish(service, store, [line], ctx)
    timing = service.timing(
        make_scene(line), VOICE_PIN, refs, "phrase", language=language, ctx=ctx
    )
    caption = timing.lines[0].caption
    assert caption.mode_used is CaptionMode.sentence
    assert caption.fallback_reason is AlignFallback.align_unavailable
    assert caption.phrases == []
