"""Assemble service: stream-copy concat with one AAC mux, SRT times and attribution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from app.plugins.registry import Registry
from app.ports import AppError, MediaInfo
from app.schemas.bgm_entry import BuiltinBgm
from app.schemas.common import Language
from app.services.assemble import AssembleService, scene_starts_ms
from app.services.render.motion import FPS, frame_count
from app.services.sound import scene_starts_ms as sound_scene_starts_ms
from tests.fixtures.media import tone_wav
from tests.media import ffmpeg
from tests.media.scenes import Ctx, Token, load, timings, video

SRT_CUE = re.compile(
    r"(\d+)\n(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})\n(.+)\n"
)


@pytest.fixture(scope="module")
def registry() -> Registry:
    loaded = Registry()
    loaded.load()
    return loaded


def _ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def test_29_srt_times_and_text_follow_the_timings(registry: Registry) -> None:
    built = video(registry)
    scene_timings = timings(built, speech_ms=1234, tail_ms=401)
    cues = SRT_CUE.findall(AssembleService(None).srt(built, scene_timings))  # type: ignore[arg-type]
    expected = [
        (start + line.start_ms, start + line.end_ms, built.scenes[timing.scene_id].lines[index])
        for start, timing in zip(scene_starts_ms(scene_timings), scene_timings, strict=True)
        for index, line in enumerate(timing.lines)
    ]
    assert len(cues) == len(expected)
    for number, (cue, (start, end, line)) in enumerate(zip(cues, expected, strict=True), 1):
        assert int(cue[0]) == number
        assert _ms(*cue[1:5]) == start and _ms(*cue[5:9]) == end
        assert cue[9] == line.display_text


def test_29_srt_scene_starts_follow_the_clip_frames(registry: Registry) -> None:
    built = video(registry)
    scene_timings = timings(built, speech_ms=1000, tail_ms=11)
    # 1011 ms is 30.33 frames: each clip has 30 frames, so scene k starts at k * 1000 ms.
    assert scene_starts_ms(scene_timings) == [index * 1000 for index in range(len(scene_timings))]


@pytest.mark.parametrize("tail_ms", [0, 1, 16, 17, 33, 401, 999])
def test_29_clip_audio_and_subtitle_clocks_use_one_frame_rule(
    registry: Registry, tail_ms: int
) -> None:
    # The rule lives in render, sound and assemble because services cannot share
    # code; this keeps the three copies from drifting apart.
    built = video(registry)
    scene_timings = timings(built, speech_ms=1000 + 7 * tail_ms, tail_ms=tail_ms)
    clip_starts, frames = [], 0
    for timing in scene_timings:
        clip_starts.append((frames * 1000 + FPS // 2) // FPS)
        frames += frame_count(timing.duration_ms)
    sound_starts, total_ms = sound_scene_starts_ms(scene_timings)
    assert scene_starts_ms(scene_timings) == sound_starts == clip_starts
    assert total_ms == (frames * 1000 + FPS // 2) // FPS


def test_29_srt_rejects_timings_out_of_scene_order(registry: Registry) -> None:
    built = video(registry)
    scene_timings = timings(built)
    with pytest.raises(AppError) as caught:
        AssembleService(None).srt(built, scene_timings[::-1])  # type: ignore[arg-type]
    assert caught.value.code == "timing_mismatch"


def _bgm(spdx: str, attribution: dict[str, str] | None) -> BuiltinBgm:
    raw = load("bgm_builtin.json")
    raw["license"]["spdx"] = spdx
    raw["license"]["attribution"] = attribution
    return BuiltinBgm.model_validate(raw)


def test_14_attribution_lists_cc_by_tracks_only() -> None:
    service = AssembleService(None)  # type: ignore[arg-type]
    cc_by = _bgm("CC-BY-4.0", {"ko": "곡 출처 문구", "en": "Track credit line"})
    unnamed = _bgm("CC-BY-3.0", None)
    cc0 = _bgm("CC0-1.0", None)
    lines = service.attributions([cc0, cc_by, unnamed, cc_by], Language.en)
    assert lines[0] == "Track credit line"
    assert lines[1].startswith('"Default calm loop" - Project authors, CC-BY-3.0, https://')
    assert len(lines) == 2
    assert service.attributions([cc_by], Language.ko) == ["곡 출처 문구"]
    assert service.attributions([cc0], Language.en) == []


class ProbeOnly:
    def __init__(self, infos: dict[str, MediaInfo]) -> None:
        self.infos = infos
        self.muxed = False

    def probe(self, src: Path) -> MediaInfo:
        return self.infos[src.name]

    def mux_concat(self, *args: Any, **kwargs: Any) -> MediaInfo:
        self.muxed = True
        raise AssertionError("mux must not run")


@pytest.mark.parametrize(
    ("clip", "reason"),
    [
        (MediaInfo(path=Path("b.mp4"), width=1080, height=1920, fps=30, sample_rate=44100),
         "clip_has_audio"),
        (MediaInfo(path=Path("b.mp4"), width=720, height=1280, fps=30), "clip_spec"),
    ],
)
def test_12_final_refuses_clips_with_sound_or_another_spec(
    tmp_path: Path, clip: MediaInfo, reason: str
) -> None:
    media = ProbeOnly(
        {
            "a.mp4": MediaInfo(path=Path("a.mp4"), width=1080, height=1920, fps=30),
            "b.mp4": clip,
            "mix.wav": MediaInfo(path=Path("mix.wav"), sample_rate=44100, channels=1),
        }
    )
    with pytest.raises(AppError) as caught:
        AssembleService(media).final(  # type: ignore[arg-type]
            [tmp_path / "a.mp4", tmp_path / "b.mp4"], tmp_path / "mix.wav", ctx=Ctx(tmp_path)
        )
    assert caught.value.detail["reason"] == reason
    assert not media.muxed


def _clip(path: Path, frames: int, shade: int) -> Path:
    data = [bytes((shade, (index * 9) % 256, 255 - shade)) * (1080 * 1920) for index in
            range(frames)]
    ffmpeg.adapter().encode_frames(
        data, width=1080, height=1920, fps=30, out=path, cancel=Token()
    )
    return path


@ffmpeg.requires_ffmpeg
def test_12_concat_copies_clip_packets_and_adds_sound_once(tmp_path: Path) -> None:
    clips = [_clip(tmp_path / "one.mp4", 12, 40), _clip(tmp_path / "two.mp4", 18, 200)]
    mix = tone_wav(tmp_path / "mix.wav", duration_ms=1000)
    out = AssembleService(ffmpeg.adapter()).final(clips, mix, ctx=Ctx(tmp_path / "job"))
    # Bit-exact frames rule out a lossy re-encode. Every packet but each clip's
    # first keyframe keeps its bytes; the muxer may repeat the parameter sets in
    # front of that keyframe when segments join.
    assert ffmpeg.decoded_frames(out) == [
        frame for clip in clips for frame in ffmpeg.decoded_frames(clip)
    ]
    joined = [ffmpeg.video_packets(clip) for clip in clips]
    packets = ffmpeg.video_packets(out)
    assert len(packets) == sum(len(clip) for clip in joined)
    offset = 0
    for clip in joined:
        assert packets[offset + 1:offset + len(clip)] == clip[1:]
        offset += len(clip)
    lines = ffmpeg.streams(out).splitlines()
    clip_video = [line for line in ffmpeg.streams(clips[0]).splitlines() if "Video:" in line]
    out_video = [line for line in lines if "Video:" in line]

    def codec(line: str) -> str:
        return re.sub(r"\d+ kb/s, ", "", line.split("Video: ", 1)[1])

    assert len(out_video) == 1 and codec(out_video[0]) == codec(clip_video[0])
    audio = [line for line in lines if "Audio:" in line]
    assert len(audio) == 1 and "aac" in audio[0] and "44100 Hz" in audio[0]
    info = ffmpeg.adapter().probe(out)
    assert (info.width, info.height, info.fps) == (1080, 1920, 30)
    assert info.duration_ms is not None and abs(info.duration_ms - 1000) <= 40
