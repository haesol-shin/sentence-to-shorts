"""Voice service tests: language estimate, per-line synthesis and timing."""

from __future__ import annotations

import hashlib
import inspect
import time
from pathlib import Path

import pytest

from app.jobs import CancelFlag, LocalJobContext
from app.ports import AlignResult, AppError, PhraseSpan, SynthResult
from app.schemas.common import ArtifactRef, CaptionMode, PinnedRef
from app.schemas.scene import Scene
from app.schemas.script import Line, Speaker
from app.schemas.voice_manifest import VoiceManifest
from app.services.voice.service import (
    LINE_GAP_MS,
    MIN_ESTIMATE_MS,
    SCENE_TAIL_MS,
    VoiceService,
)
from app.tools.tts.fixed_wav.adapter import FixedWavTts
from tests.conftest import load_json
from tests.fixtures.media import tone_wav

SCENE_ID = "s_0nzvrzf0tp9wba44f6yvh6nzpr"
LINE_IDS = (
    "l_079jmk94bf8vj82ct90jqj44km",
    "l_079jmk94bf8vj82ct90jqj44kn",
    "l_079jmk94bf8vj82ct90jqj44kp",
)
ARTIFACT_IDS = (
    "a_079jmk94bf8vj82ct90jqj44km",
    "a_079jmk94bf8vj82ct90jqj44kn",
    "a_079jmk94bf8vj82ct90jqj44kp",
)
VOICE_PIN = PinnedRef(
    id="fixed_wav",
    revision="ba110776c483d72203c4546080a8b32a277f4b22bf81af8781936685a226c768",
)


class FakeAligner:
    """Returns a configured result per speech text and records each call."""

    def __init__(self, results: dict[str, AlignResult] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[Path, str, str, str]] = []

    def align(
        self,
        wav: Path,
        speech_text: str,
        display_text: str,
        language: str,
        *,
        cancel,
    ) -> AlignResult:
        self.calls.append((wav, speech_text, display_text, language))
        return self.results.get(
            speech_text,
            AlignResult(phrases=None, failure="align_failed"),
        )


class FakeArtifactStore:
    """Resolves a published TTS ref to the WAV a test wrote."""

    def __init__(self) -> None:
        self.files: dict[str, Path] = {}

    def publish(self, artifact_id: str, path: Path) -> ArtifactRef:
        self.files[artifact_id] = path
        data = path.read_bytes()
        return ArtifactRef(
            id=artifact_id,
            digest=hashlib.sha256(data).hexdigest(),
            cache_key=hashlib.sha256(f"{artifact_id}|{len(data)}".encode()).hexdigest(),
        )

    def path(self, artifact_id: str) -> Path:
        return self.files[artifact_id]


class RecordingTts(FixedWavTts):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, VoiceManifest]] = []

    def synthesize(
        self,
        text: str,
        language: str,
        voice: VoiceManifest,
        *,
        out_dir: Path,
        cancel,
    ) -> SynthResult:
        self.calls.append((text, language, voice))
        return super().synthesize(text, language, voice, out_dir=out_dir, cancel=cancel)


class BrokenTts:
    def __init__(self, code: str) -> None:
        self.code = code

    def synthesize(self, text, language, voice, *, out_dir, cancel) -> SynthResult:
        raise AppError(self.code)


def fixed_voice() -> VoiceManifest:
    return VoiceManifest.model_validate(load_json("contracts/valid/voice_fixed_wav.json"))


def make_ctx(tmp_path: Path) -> LocalJobContext:
    return LocalJobContext(
        cancel_token=CancelFlag(),
        deadline=time.monotonic() + 60,
        job_dir=tmp_path / "job",
    )


def make_line(index: int, display_text: str, speech_text: str | None = None) -> Line:
    return Line(
        id=LINE_IDS[index],
        display_text=display_text,
        speech_text=display_text if speech_text is None else speech_text,
        speaker=Speaker.narrator,
        highlight=[],
    )


def make_scene(*lines: Line) -> Scene:
    return Scene(
        id=SCENE_ID,
        beat_id="hook",
        beat_label="훅",
        lines=list(lines),
        visual=None,
    )


def make_service(aligner: FakeAligner | None = None) -> tuple[VoiceService, FakeArtifactStore]:
    store = FakeArtifactStore()
    return VoiceService(FixedWavTts(), aligner or FakeAligner(), store), store


def synthesize(service: VoiceService, line: Line, ctx: LocalJobContext) -> Path:
    return service.synthesize(fixed_voice(), "ko", line, ctx=ctx)


def publish(
    service: VoiceService,
    store: FakeArtifactStore,
    lines: list[Line],
    ctx: LocalJobContext,
) -> dict[str, ArtifactRef]:
    refs: dict[str, ArtifactRef] = {}
    for index, line in enumerate(lines):
        refs[line.id] = store.publish(ARTIFACT_IDS[index], synthesize(service, line, ctx))
    return refs


def test_estimate_ms_uses_the_language_rate_table() -> None:
    service, _ = make_service()
    text = "가나다라마바사아자차"
    line = make_line(0, text)
    korean = service.estimate_ms(line, "ko")
    english = service.estimate_ms(line, "en")
    assert korean > english
    assert service.estimate_ms(make_line(1, "가"), "ko") == MIN_ESTIMATE_MS
    assert service.estimate_ms(make_line(1, "   "), "ko") == MIN_ESTIMATE_MS
    with pytest.raises(ValueError):
        service.estimate_ms(line, "fr")


def test_11_display_edit_keeps_the_same_tts_wav(tmp_path: Path) -> None:
    service, _ = make_service()
    ctx = make_ctx(tmp_path)
    first = synthesize(service, make_line(0, "한 가지", "세 가지"), ctx)
    second = synthesize(service, make_line(1, "완전히 다른 화면 글", "세 가지"), ctx)
    assert first == second


def test_9_two_videos_pin_the_same_voice(tmp_path: Path) -> None:
    tts = RecordingTts()
    store = FakeArtifactStore()
    service = VoiceService(tts, FakeAligner(), store)
    voice = fixed_voice()
    line = make_line(0, "세 가지", "세 가지")
    timings = []
    for name in ("a", "b"):
        ctx = make_ctx(tmp_path / name)
        ref = store.publish(ARTIFACT_IDS[0], service.synthesize(voice, "ko", line, ctx=ctx))
        timings.append(
            service.timing(make_scene(line), VOICE_PIN, {line.id: ref}, "sentence", "ko", ctx=ctx)
        )
    assert timings[0].voice == timings[1].voice == VOICE_PIN
    assert [call[1] for call in tts.calls] == ["ko", "ko"]
    assert [call[2] for call in tts.calls] == [voice, voice]


def test_15_timing_records_the_published_refs(tmp_path: Path) -> None:
    service, store = make_service()
    ctx = make_ctx(tmp_path)
    lines = [make_line(0, "가나다"), make_line(1, "라마바")]
    refs = publish(service, store, lines, ctx)
    timing = service.timing(make_scene(*lines), VOICE_PIN, refs, "sentence", "ko", ctx=ctx)
    assert timing.schema_version == 2
    assert timing.scene_id == SCENE_ID
    assert timing.voice == VOICE_PIN
    assert [line.tts for line in timing.lines] == [refs[line.id] for line in lines]


def test_15_phrase_spans_stay_inside_display_text(tmp_path: Path) -> None:
    display = "A1 스타트"
    speech = "에이 원 스타트"
    phrases = [
        PhraseSpan(start_char=0, end_char=2, start_ms=0, end_ms=200),
        PhraseSpan(start_char=2, end_char=3, start_ms=200, end_ms=260),
        PhraseSpan(start_char=3, end_char=6, start_ms=260, end_ms=700),
    ]
    aligner = FakeAligner({speech: AlignResult(phrases=phrases, failure=None)})
    service, store = make_service(aligner)
    ctx = make_ctx(tmp_path)
    line = make_line(0, display, speech)
    refs = publish(service, store, [line], ctx)
    timing = service.timing(
        make_scene(line), VOICE_PIN, refs, "phrase", "ko", ctx=ctx
    )
    caption = timing.lines[0].caption
    assert caption.mode_used is CaptionMode.phrase
    assert caption.fallback_reason is None
    assert len(caption.phrases) == len(phrases)
    for phrase in caption.phrases:
        assert 0 <= phrase.start_char < phrase.end_char <= len(display)
        assert 0 <= phrase.start_ms < phrase.end_ms <= timing.lines[0].speech_ms
    assert aligner.calls == [(store.path(refs[line.id].id), speech, display, "ko")]


def test_15_failed_line_falls_back_to_sentence(tmp_path: Path) -> None:
    first, second = "첫 줄", "둘째 줄"
    first_phrases = [
        PhraseSpan(start_char=0, end_char=1, start_ms=0, end_ms=150),
        PhraseSpan(start_char=1, end_char=3, start_ms=150, end_ms=290),
    ]
    aligner = FakeAligner(
        {
            first: AlignResult(phrases=first_phrases, failure=None),
            second: AlignResult(phrases=None, failure="align_low_confidence"),
        }
    )
    service, store = make_service(aligner)
    ctx = make_ctx(tmp_path)
    lines = [make_line(0, first), make_line(1, second)]
    refs = publish(service, store, lines, ctx)
    timing = service.timing(make_scene(*lines), VOICE_PIN, refs, "phrase", "ko", ctx=ctx)
    assert timing.lines[0].caption.mode_used is CaptionMode.phrase
    assert timing.lines[0].caption.fallback_reason is None
    failed = timing.lines[1]
    assert failed.caption.mode_used is CaptionMode.sentence
    assert failed.caption.fallback_reason == "align_low_confidence"
    assert failed.caption.phrases == []
    assert failed.end_ms - failed.start_ms == failed.speech_ms


def test_15_failed_alignment_never_builds_times_from_characters(tmp_path: Path) -> None:
    speech = "짧은 말"
    aligner = FakeAligner({speech: AlignResult(phrases=None, failure="align_failed")})
    service, store = make_service(aligner)
    ctx = make_ctx(tmp_path)
    long_line = make_line(0, "아주 긴 화면 글자" * 3, speech)
    short_line = make_line(1, "짧", speech)
    lines = [long_line, short_line]
    refs = publish(service, store, lines, ctx)
    timing = service.timing(make_scene(*lines), VOICE_PIN, refs, "phrase", "ko", ctx=ctx)
    for result in timing.lines:
        assert result.caption.mode_used is CaptionMode.sentence
        assert result.caption.fallback_reason == "align_failed"
        assert result.caption.phrases == []
        assert result.end_ms - result.start_ms == result.speech_ms
    assert len(aligner.calls) == 2


@pytest.mark.parametrize(
    "phrases",
    [
        [PhraseSpan(start_char=0, end_char=4, start_ms=0, end_ms=100)],
        [PhraseSpan(start_char=0, end_char=3, start_ms=0, end_ms=999)],
    ],
)
def test_15_invalid_alignment_falls_back_to_sentence(
    tmp_path: Path, phrases: list[PhraseSpan]
) -> None:
    text = "가나다"
    aligner = FakeAligner({text: AlignResult(phrases=phrases, failure=None)})
    service, store = make_service(aligner)
    ctx = make_ctx(tmp_path)
    line = make_line(0, text)
    refs = publish(service, store, [line], ctx)
    timing = service.timing(
        make_scene(line), VOICE_PIN, refs, "phrase", "ko", ctx=ctx
    )
    caption = timing.lines[0].caption
    assert caption.mode_used is CaptionMode.sentence
    assert caption.fallback_reason == "align_failed"
    assert caption.phrases == []


def test_15_typewriter_spans_cover_each_grapheme_and_follow_the_formula(
    tmp_path: Path,
) -> None:
    display = "👩\u200d💻가!"
    speech = "짧은 말"
    service, store = make_service()
    ctx = make_ctx(tmp_path)
    line = make_line(0, display, speech)
    refs = publish(service, store, [line], ctx)
    timing = service.timing(
        make_scene(line), VOICE_PIN, refs, "typewriter", "ko", ctx=ctx
    )
    first = timing.lines[0]
    phrases = first.caption.phrases
    shown = first.end_ms - first.start_ms
    assert first.caption.mode_used is CaptionMode.typewriter
    assert first.caption.fallback_reason is None
    assert shown >= first.speech_ms
    assert [(phrase.start_char, phrase.end_char) for phrase in phrases] == [
        (0, 3),
        (3, 4),
        (4, 5),
    ]
    assert phrases[0].start_ms == first.start_ms
    assert phrases[-1].end_ms == first.end_ms
    for index, phrase in enumerate(phrases):
        assert phrase.start_ms == first.start_ms + index * shown // len(phrases)
        assert phrase.end_ms == first.start_ms + (index + 1) * shown // len(phrases)


def test_15_typewriter_keeps_a_short_line_at_its_speech_length(tmp_path: Path) -> None:
    speech = "짧은 말"
    service, store = make_service()
    ctx = make_ctx(tmp_path)
    line = make_line(0, "짧", speech)
    refs = publish(service, store, [line], ctx)
    timing = service.timing(
        make_scene(line), VOICE_PIN, refs, "typewriter", "ko", ctx=ctx
    )
    first = timing.lines[0]
    assert first.end_ms - first.start_ms == first.speech_ms
    assert first.caption.phrases[0].end_ms == first.end_ms


def test_15_timing_requires_the_video_language() -> None:
    parameters = inspect.signature(VoiceService.timing).parameters
    assert "language" in parameters
    assert parameters["language"].default is inspect.Parameter.empty


def test_15_line_gap_and_scene_tail_follow_the_defaults(tmp_path: Path) -> None:
    service, store = make_service()
    ctx = make_ctx(tmp_path)
    lines = [make_line(0, "가나다"), make_line(1, "라마바")]
    refs = publish(service, store, lines, ctx)
    timing = service.timing(make_scene(*lines), VOICE_PIN, refs, "sentence", "ko", ctx=ctx)
    assert timing.lines[0].start_ms == 0
    assert timing.lines[1].start_ms == timing.lines[0].end_ms + LINE_GAP_MS
    assert timing.duration_ms == timing.lines[-1].end_ms + SCENE_TAIL_MS


def test_15_phrase_times_follow_the_scene_clock(tmp_path: Path) -> None:
    display = "가나다"
    speech = "가나다라마바사아자차"
    phrases = [PhraseSpan(start_char=0, end_char=3, start_ms=0, end_ms=200)]
    aligner = FakeAligner({speech: AlignResult(phrases=phrases, failure=None)})
    service, store = make_service(aligner)
    ctx = make_ctx(tmp_path)
    lines = [make_line(0, display, speech), make_line(1, display, speech)]
    refs = publish(service, store, lines, ctx)
    timing = service.timing(make_scene(*lines), VOICE_PIN, refs, "phrase", "ko", ctx=ctx)
    first, second = timing.lines
    assert first.caption.phrases[0].start_ms == 0
    assert first.caption.phrases[0].end_ms == 200
    assert second.start_ms == first.end_ms + LINE_GAP_MS
    assert second.caption.phrases[0].start_ms == second.start_ms
    assert second.caption.phrases[0].end_ms == second.start_ms + 200


def test_15_truncated_wav_keeps_tts_failed(tmp_path: Path) -> None:
    service, store = make_service()
    line = make_line(0, "가나다")
    path = tone_wav(tmp_path / "cut.wav", duration_ms=1000)
    path.write_bytes(path.read_bytes()[:44])
    ref = store.publish(ARTIFACT_IDS[0], path)
    with pytest.raises(AppError) as error:
        service.timing(
            make_scene(line), VOICE_PIN, {line.id: ref}, "sentence", "ko", ctx=make_ctx(tmp_path)
        )
    assert error.value.code == "tts_failed"


def test_15_missing_tts_keeps_tts_failed(tmp_path: Path) -> None:
    service, _ = make_service()
    line = make_line(0, "가나다")
    with pytest.raises(AppError) as error:
        service.timing(
            make_scene(line), VOICE_PIN, {}, "sentence", "ko", ctx=make_ctx(tmp_path)
        )
    assert error.value.code == "tts_failed"


def test_15_unknown_artifact_keeps_tts_failed(tmp_path: Path) -> None:
    service, _ = make_service()
    line = make_line(0, "가나다")
    lost = ArtifactRef(id=ARTIFACT_IDS[0], digest="0" * 64, cache_key="1" * 64)
    with pytest.raises(AppError) as error:
        service.timing(
            make_scene(line), VOICE_PIN, {line.id: lost}, "sentence", "ko", ctx=make_ctx(tmp_path)
        )
    assert error.value.code == "tts_failed"


def test_synthesize_keeps_the_tts_timeout_code(tmp_path: Path) -> None:
    service = VoiceService(BrokenTts("tts_timeout"), FakeAligner(), FakeArtifactStore())
    line = make_line(0, "가나다")
    with pytest.raises(AppError) as error:
        service.synthesize(fixed_voice(), "ko", line, ctx=make_ctx(tmp_path))
    assert error.value.code == "tts_timeout"
