"""Sound service: BGM pick, loop seams, upload import and the video mix."""

from __future__ import annotations

import io
import math
import wave
from array import array
from pathlib import Path
from typing import Any

import pytest

from app.plugins.registry import Registry
from app.ports import AppError, MediaInfo, MixItem, MixPlan, scene_starts_ms
from app.schemas.artifact import Timing
from app.schemas.bgm_entry import UploadBgm
from app.schemas.settings import Settings
from app.schemas.video import Video
from app.services.sound import SoundService, loop_samples
from app.services.sound.service import typing_gain_db_x10, typing_key_index
from tests.conftest import load_json
from tests.fixtures.media import corrupt_wav, tone_wav
from tests.media import ffmpeg
from tests.media.scenes import Ctx, Token, timings, tts_tones, video

RATE = 44100
LIMIT_BYTES = 31_457_280
LIMIT_MS = 600_000


@pytest.fixture(scope="module")
def registry() -> Registry:
    loaded = Registry()
    loaded.load()
    return loaded


class NoMedia:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"media.{name} must not be called")


class NoSubmit:
    def submit(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("submitter.submit must not be called")


def _service(
    registry: Registry,
    media: Any = None,
    *,
    submitter: Any = None,
    staging_dir: Path | None = None,
    **limits: int,
) -> SoundService:
    return SoundService(
        media if media is not None else NoMedia(),
        registry,
        submitter if submitter is not None else NoSubmit(),
        staging_dir=staging_dir or Path("staging"),
        max_upload_bytes=limits.get("max_upload_bytes", LIMIT_BYTES),
        max_upload_ms=limits.get("max_upload_ms", LIMIT_MS),
    )


def _settings(registry: Registry, mood: str) -> Settings:
    built = video(registry)
    raw = built.settings.model_dump(mode="json", by_alias=True)
    raw["audio"]["bgm"]["mood"] = mood
    return Settings.model_validate(raw)


def _typing_video(*, sfx_enabled: bool = True, typing_sound: bool = True) -> Video:
    built = Video.model_validate(
        load_json("contracts/valid/video_ko_typewriter_typing.json")
    )
    caption = built.settings.caption
    if not typing_sound:
        caption = caption.model_copy(update={"typing_sound": None})
    bgm = built.settings.audio.bgm.model_copy(update={"enabled": False})
    audio = built.settings.audio.model_copy(
        update={"bgm": bgm, "sfx_enabled": sfx_enabled}
    )
    return built.model_copy(
        update={
            "settings": built.settings.model_copy(
                update={"audio": audio, "caption": caption}
            )
        }
    )


def _typing_timing() -> Timing:
    return Timing.model_validate(load_json("contracts/valid/timing_typewriter.json"))


class PlanRecorder:
    """Records the mix plan; BGM is off so no audio file is read."""

    def __init__(self) -> None:
        self.plan: MixPlan | None = None

    def decode_audio(self, *args: Any, **kwargs: Any) -> MediaInfo:
        raise AssertionError("the typing mix test reads no source audio")

    def mix(self, plan: MixPlan, *, out: Path, cancel: Any) -> MediaInfo:
        self.plan = plan
        out.write_bytes(b"")
        return MediaInfo(path=out)


def _samples(path: Path) -> array:
    with wave.open(str(path), "rb") as handle:
        assert handle.getframerate() == RATE and handle.getnchannels() == 1
        data = array("h")
        data.frombytes(handle.readframes(handle.getnframes()))
    return data


def _rms(samples: array, start_ms: int, end_ms: int) -> float:
    window = samples[start_ms * RATE // 1000:end_ms * RATE // 1000]
    return math.sqrt(sum(value * value for value in window) / len(window))


def _sine(frames: int, frequency: float, amplitude: float = 0.5) -> array:
    return array(
        "h",
        (round(amplitude * 32767 * math.sin(2 * math.pi * frequency * index / RATE))
         for index in range(frames)),
    )


def test_14_loop_seam_leaves_no_sample_step() -> None:
    source = _sine(39_725, 441.0)
    largest_step = max(abs(b - a) for a, b in zip(source, source[1:], strict=False))
    naive = source + source
    seam_step = abs(naive[len(source)] - naive[len(source) - 1])
    assert seam_step > 5 * largest_step
    looped = [value * 32768 for value in loop_samples(source, 5 * len(source), 22_050)]
    assert len(looped) == 5 * len(source)
    steps = max(abs(b - a) for a, b in zip(looped, looped[1:], strict=False))
    # Equal-power gains add up to at most sqrt(2) on correlated material; a step
    # from a cut loop would be the naive seam step, many times larger.
    assert steps <= math.sqrt(2) * largest_step + 2


def test_14_loop_keeps_level_through_the_crossfade() -> None:
    source = _sine(44_100, 220.0)
    looped = [value * 32768 for value in loop_samples(source, 4 * len(source), 22_050)]
    level = math.sqrt(sum(value * value for value in source) / len(source))
    for start in range(0, len(looped) - 4410, 4410):
        window = looped[start:start + 4410]
        assert math.sqrt(sum(value * value for value in window) / len(window)) > 0.5 * level


def test_14_loud_loop_seam_keeps_its_peaks_unclipped() -> None:
    # 441 whole cycles and an 11,000-sample crossfade: the overlapping samples are
    # equal, so the crossfade sums correlated material and peaks near sqrt(2)
    # times the 0.95 source level.
    source = _sine(44_100, 441.0, amplitude=0.95)
    looped = loop_samples(source, 3 * len(source), 11_000)
    peak = max(abs(value) for value in looped)
    assert peak > 1.0
    assert peak == pytest.approx(0.95 * math.sqrt(2), rel=0.02)


@ffmpeg.requires_ffmpeg
def test_14_mix_does_not_clip_a_sum_above_full_scale(tmp_path: Path) -> None:
    tone = tone_wav(tmp_path / "tone.wav", duration_ms=2000, frequency=441.0)
    # Two in-phase 0.2 tones raised 9 dB sum to about 1.13 times full scale.
    plan = MixPlan(items=[MixItem(path=tone, start_ms=0, gain_db_x10=90)] * 2, duration_ms=2000)
    out = ffmpeg.adapter().mix(plan, out=tmp_path / "mix.wav", cancel=Token())
    samples = _samples(out.path)[RATE // 2:3 * RATE // 2]
    peak = max(abs(value) for value in samples)
    near_peak = sum(1 for value in samples if abs(value) >= 0.99 * peak)
    # A clean sine spends about 9% of its samples within 1% of its peak; a sine
    # clipped at 1/1.13 of its level and then scaled spends about 30% there.
    assert near_peak / len(samples) < 0.2


def test_14_pick_bgm_is_seeded_and_skips_recent_tracks(registry: Registry) -> None:
    service = _service(registry)
    settings = _settings(registry, "curious")
    first = service.pick_bgm(settings, [], 7)
    assert first == service.pick_bgm(settings, [], 7)
    assert registry.get("bgm", first.id).mood.value == "curious"
    other = service.pick_bgm(settings, [first.id], 7)
    assert other.id != first.id
    assert registry.get("bgm", other.id).mood.value == "curious"
    assert service.pick_bgm(settings, [other.id, first.id], 7).id == first.id
    picks = {service.pick_bgm(settings, [], seed).id for seed in range(20)}
    assert len(picks) == 2


def test_14_upload_over_the_byte_limit_is_rejected_before_decoding(
    registry: Registry, tmp_path: Path
) -> None:
    src = tone_wav(tmp_path / "x", duration_ms=1000)
    service = _service(registry, max_upload_bytes=1000)
    with pytest.raises(AppError) as caught:
        service.import_upload(src, "p_06pxfteaw88hs93kkckw5j51ng", ctx=Ctx(tmp_path / "job"))
    assert caught.value.code == "upload_invalid"
    assert caught.value.detail["reason"] == "too_large"


@ffmpeg.requires_ffmpeg
def test_14_corrupt_upload_is_upload_invalid(registry: Registry, tmp_path: Path) -> None:
    src = corrupt_wav(tmp_path / "broken")
    service = _service(registry, ffmpeg.adapter())
    with pytest.raises(AppError) as caught:
        service.import_upload(src, "p_06pxfteaw88hs93kkckw5j51ng", ctx=Ctx(tmp_path / "job"))
    assert caught.value.code == "upload_invalid"
    assert not list((tmp_path / "job").rglob("*.wav"))


@ffmpeg.requires_ffmpeg
def test_14_upload_over_the_length_limit_is_rejected(registry: Registry, tmp_path: Path) -> None:
    src = tone_wav(tmp_path / "long", duration_ms=3000)
    service = _service(registry, ffmpeg.adapter(), max_upload_ms=2000)
    with pytest.raises(AppError) as caught:
        service.import_upload(src, "p_06pxfteaw88hs93kkckw5j51ng", ctx=Ctx(tmp_path / "job"))
    assert caught.value.code == "upload_invalid"
    assert caught.value.detail["reason"] == "too_long"


@ffmpeg.requires_ffmpeg
def test_14_upload_becomes_44k_mono_wav_named_by_its_upload_id(
    registry: Registry, tmp_path: Path
) -> None:
    src = tone_wav(tmp_path / "my holiday song.wav", duration_ms=1500, sample_rate=48000,
                   channels=2)
    ctx = Ctx(tmp_path / "job")
    entry = _service(registry, ffmpeg.adapter()).import_upload(
        src, "p_06pxfteaw88hs93kkckw5j51ng", ctx=ctx
    )
    assert isinstance(entry, UploadBgm)
    assert entry.id == entry.upload_id and entry.file == f"{entry.upload_id}.wav"
    assert (entry.sample_rate, entry.channels, entry.original_bytes) == (
        RATE, 1, src.stat().st_size
    )
    assert abs(entry.duration_ms - 1500) <= 2
    stored = list(ctx.job_dir.rglob("*.wav"))
    assert [path.name for path in stored] == [entry.file]
    assert "holiday" not in entry.model_dump_json()
    assert len(_samples(stored[0])) == pytest.approx(1.5 * RATE, abs=100)


@ffmpeg.requires_ffmpeg
def test_14_mix_meets_loudness_and_true_peak_targets(registry: Registry, tmp_path: Path) -> None:
    built = video(registry)
    scene_timings = timings(built)
    tts = tts_tones(built, tmp_path / "tts")
    out = _service(registry, ffmpeg.adapter()).mix(
        built, scene_timings, tts, ctx=Ctx(tmp_path / "job")
    )
    integrated, true_peak = ffmpeg.loudness(out)
    assert -17.0 <= integrated <= -15.0
    assert true_peak <= -1.0
    _, total_ms = scene_starts_ms(scene_timings)
    assert abs(len(_samples(out)) * 1000 // RATE - total_ms) <= 2


@ffmpeg.requires_ffmpeg
def test_14_bgm_keeps_playing_across_scene_boundaries(registry: Registry, tmp_path: Path) -> None:
    built = video(registry)
    scene_timings = timings(built)
    tts = tts_tones(built, tmp_path / "tts")
    out = _service(registry, ffmpeg.adapter()).mix(
        built, scene_timings, tts, ctx=Ctx(tmp_path / "job")
    )
    samples = _samples(out)
    starts, _ = scene_starts_ms(scene_timings)
    floor = 32767 * 10 ** (-50 / 20)
    for boundary in starts[1:]:
        assert _rms(samples, boundary - 150, boundary - 50) > floor


@ffmpeg.requires_ffmpeg
def test_14_mix_without_bgm_still_spans_the_video(registry: Registry, tmp_path: Path) -> None:
    built = video(registry, enabled=False)
    scene_timings = timings(built)
    tts = tts_tones(built, tmp_path / "tts")
    out = _service(registry, ffmpeg.adapter()).mix(
        built, scene_timings, tts, ctx=Ctx(tmp_path / "job")
    )
    _, total_ms = scene_starts_ms(scene_timings)
    assert abs(len(_samples(out)) * 1000 // RATE - total_ms) <= 2


class MixRecorder:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.plan: Any = None

    def decode_audio(self, *args: Any, **kwargs: Any) -> MediaInfo:
        return self.inner.decode_audio(*args, **kwargs)

    def mix(self, plan: Any, *, out: Path, cancel: Any) -> MediaInfo:
        self.plan = plan
        out.write_bytes(b"")
        return MediaInfo(path=out)


@ffmpeg.requires_ffmpeg
def test_14_lines_and_effects_sit_on_the_scene_clock(registry: Registry, tmp_path: Path) -> None:
    built = video(registry)
    scene_timings = timings(built)
    tts = tts_tones(built, tmp_path / "tts")
    recorder = MixRecorder(ffmpeg.adapter())
    _service(registry, recorder).mix(built, scene_timings, tts, ctx=Ctx(tmp_path / "job"))
    starts, _ = scene_starts_ms(scene_timings)
    bed, *rest = recorder.plan.items
    assert bed.ducking_db_x10 < 0 and bed.gain_db_x10 == built.settings.audio.bgm.gain_db_x10
    voice = [item for item in rest if item.path.parent.name == "tts"]
    assert [item.start_ms for item in voice] == starts
    effects = [item for item in rest if item.path.parent.name != "tts"]
    sfx_scene = built.scene_order.index(
        next(sid for sid in built.scene_order if built.scenes[sid].visual.sfx)
    )
    assert [item.start_ms for item in effects] == [starts[sfx_scene]]


def _typing_plan(
    registry: Registry, tmp_path: Path, built: Video, timing: Timing
) -> MixPlan:
    recorder = PlanRecorder()
    tts = {timing.lines[0].line_id: tmp_path / "tts" / "line.wav"}
    _service(registry, recorder).mix(
        built, [timing], tts, ctx=Ctx(tmp_path / "job")
    )
    assert recorder.plan is not None
    return recorder.plan


def _keys(plan: MixPlan) -> list[MixItem]:
    return [item for item in plan.items if item.path.parent.name.startswith("typing_")]


def test_14_typing_sound_places_one_key_per_voiced_span(
    registry: Registry, tmp_path: Path
) -> None:
    built = _typing_video()
    timing = _typing_timing()
    plan = _typing_plan(registry, tmp_path, built, timing)
    keys = _keys(plan)
    # The display text is "타자!": punctuation makes no sound.
    assert [item.start_ms for item in keys] == [0, 666]
    assert len({item.path for item in keys}) == 2
    assert all(-50 <= item.gain_db_x10 <= 0 for item in keys)
    assert plan.duration_ms == scene_starts_ms([timing])[1]
    assert [item.start_ms for item in plan.items if item.path.parent.name == "tts"] == [0]


def test_14_typing_sound_is_deterministic(
    registry: Registry, tmp_path: Path
) -> None:
    built = _typing_video()
    timing = _typing_timing()
    first = _keys(_typing_plan(registry, tmp_path / "a", built, timing))
    second = _keys(_typing_plan(registry, tmp_path / "b", built, timing))
    assert [(item.path, item.gain_db_x10) for item in first] == [
        (item.path, item.gain_db_x10) for item in second
    ]


def test_14_typing_sound_follows_the_sfx_switch_and_caption_setting(
    registry: Registry, tmp_path: Path
) -> None:
    timing = _typing_timing()
    off = _typing_plan(
        registry, tmp_path / "off", _typing_video(sfx_enabled=False), timing
    )
    silent = _typing_plan(
        registry, tmp_path / "silent", _typing_video(typing_sound=False), timing
    )
    assert _keys(off) == []
    assert _keys(silent) == []


def test_14_typing_key_choice_skips_the_previous_key_and_repeats_one_key() -> None:
    assert typing_key_index("l_x", 0, "a" * 64, 1, None) == 0
    assert typing_key_index("l_x", 3, "a" * 64, 1, 0) == 0
    previous = None
    chosen = []
    for start in range(20):
        index = typing_key_index("l_x", start, "a" * 64, 2, previous)
        assert index != previous
        chosen.append(index)
        previous = index
    assert set(chosen) == {0, 1}


def test_14_typing_gain_stays_inside_its_range() -> None:
    gains = {typing_gain_db_x10("l_x", start, "a" * 64) for start in range(200)}
    assert min(gains) >= -50 and max(gains) <= 0


@ffmpeg.requires_ffmpeg
def test_14_mix_output_is_cut_at_the_plan_duration(tmp_path: Path) -> None:
    tone = tone_wav(tmp_path / "tone.wav", duration_ms=2000, frequency=441.0)
    plan = MixPlan(items=[MixItem(path=tone, start_ms=0)], duration_ms=1000)
    out = ffmpeg.adapter().mix(plan, out=tmp_path / "cut.wav", cancel=Token())
    assert out.duration_ms is not None
    assert abs(out.duration_ms - 1000) <= 50


class RecordingSubmitter:
    def __init__(self, status: int = 202) -> None:
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def submit(self, kind: Any, **kwargs: Any) -> Any:
        from app.ports import SubmitResult
        from tests.jobs.support import new_job

        self.calls.append({"kind": kind, **kwargs})
        return SubmitResult(job=new_job(kind), status=self.status)


def _upload(data: bytes) -> Any:
    from app.ports import UploadSource

    return UploadSource("synthetic.wav", "audio/wav", io.BytesIO(data))


def test_39_upload_is_staged_and_the_mood_reaches_the_job_input(
    registry: Registry, tmp_path: Path
) -> None:
    from app.schemas.common import Mood
    from app.schemas.job import JobKind

    submitter = RecordingSubmitter()
    staging = tmp_path / "staging" / "bgm"
    service = _service(registry, submitter=submitter, staging_dir=staging)
    result = service.submit_upload(
        "p_06pxfteaw88hs93kkckw5j51ng", _upload(b"synthetic audio"), Mood.curious, "key-00000001"
    )
    assert result.status == 202
    call = submitter.calls[0]
    assert call["kind"] is JobKind.bgm_upload
    assert call["project_id"] == "p_06pxfteaw88hs93kkckw5j51ng"
    assert call["input"]["mood"] == "curious"
    assert call["input"]["project_id"] == "p_06pxfteaw88hs93kkckw5j51ng"
    staged = Path(call["input"]["staging_path"])
    assert staged.parent == staging
    assert staged.read_bytes() == b"synthetic audio"
    assert staged.name == call["input"]["upload_id"]


def test_39_upload_over_the_limit_is_stopped_and_the_partial_file_removed(
    registry: Registry, tmp_path: Path
) -> None:
    from app.schemas.common import Mood

    submitter = RecordingSubmitter()
    staging = tmp_path / "staging" / "bgm"
    service = _service(
        registry, submitter=submitter, staging_dir=staging, max_upload_bytes=4
    )
    with pytest.raises(AppError) as caught:
        service.submit_upload(
            "p_06pxfteaw88hs93kkckw5j51ng", _upload(b"too many bytes"), Mood.calm, "key-00000001"
        )
    assert caught.value.code == "payload_too_large"
    assert list(staging.iterdir()) == []
    assert submitter.calls == []


def test_39_reused_job_deletes_the_newly_received_file(
    registry: Registry, tmp_path: Path
) -> None:
    from app.schemas.common import Mood

    submitter = RecordingSubmitter(status=200)
    staging = tmp_path / "staging" / "bgm"
    service = _service(registry, submitter=submitter, staging_dir=staging)
    service.submit_upload(
        "p_06pxfteaw88hs93kkckw5j51ng", _upload(b"synthetic audio"), Mood.calm, "key-00000001"
    )
    assert list(staging.iterdir()) == []


@ffmpeg.requires_ffmpeg
def test_39_import_upload_records_the_stored_mood(registry: Registry, tmp_path: Path) -> None:
    from app.schemas.common import Mood

    src = tone_wav(tmp_path / "tone", duration_ms=1500)
    entry = _service(registry, ffmpeg.adapter()).import_upload(
        src,
        "p_06pxfteaw88hs93kkckw5j51ng",
        ctx=Ctx(tmp_path / "job"),
        mood=Mood.tense,
    )
    assert entry.mood is Mood.tense


@ffmpeg.requires_ffmpeg
def test_39_import_upload_without_a_mood_uses_calm(registry: Registry, tmp_path: Path) -> None:
    from app.schemas.common import Mood

    src = tone_wav(tmp_path / "tone", duration_ms=1500)
    entry = _service(registry, ffmpeg.adapter()).import_upload(
        src, "p_06pxfteaw88hs93kkckw5j51ng", ctx=Ctx(tmp_path / "job")
    )
    assert entry.mood is Mood.calm
