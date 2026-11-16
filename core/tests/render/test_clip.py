"""Scene clips: frame count and length, poses from timing, silent encode."""

from __future__ import annotations

import copy
import hashlib
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from app.ports import AppError, MediaInfo
from app.schemas.artifact import Timing
from app.schemas.text import clusters
from app.services.render import RenderService
from app.services.render.motion import (
    SCALE_STEP,
    caption_state,
    frame_count,
    poses,
)
from app.services.render.service import OUTPUT, _typed
from app.services.render.text import fit, units
from tests.media import ffmpeg
from tests.render.conftest import Ctx, Studio, Token, load

TTS_REF = load("timing_sentence_fallback.json")["lines"][0]["tts"]
FRAME_BYTES = OUTPUT[0] * OUTPUT[1] * 3


def timing_for(
    scene: dict[str, Any],
    *,
    speech_ms: int = 600,
    gap_ms: int = 200,
    tail_ms: int = 200,
    mode: str = "sentence",
    phrases: list[list[dict[str, int]]] | None = None,
) -> Timing:
    lines = []
    cursor = 0
    for index, line in enumerate(scene["lines"]):
        start = 0 if index == 0 else cursor + gap_ms
        lines.append(
            {
                "line_id": line["id"],
                "tts": TTS_REF,
                "start_ms": start,
                "end_ms": start + speech_ms,
                "speech_ms": speech_ms,
                "caption": {
                    "mode_used": mode,
                    "fallback_reason": None,
                    "phrases": phrases[index] if phrases else [],
                },
            }
        )
        cursor = start + speech_ms
    return Timing.model_validate(
        {
            "schema_version": 2,
            "scene_id": scene["id"],
            "voice": load("timing_sentence_fallback.json")["voice"],
            "duration_ms": cursor + tail_ms,
            "lines": lines,
        }
    )


class FrameSink:
    """Media port double that consumes the frame stream like the encoder."""

    def __init__(self) -> None:
        self.count = 0
        self.first = b""
        self.last = b""
        self.distinct: set[str] = set()

    def encode_frames(
        self, frames: Iterable[bytes], *, width: int, height: int, fps: int, out: Path, cancel: Any
    ) -> MediaInfo:
        assert (width, height, fps) == (1080, 1920, 30)
        for frame in frames:
            assert len(frame) == FRAME_BYTES
            if not self.count:
                self.first = frame
            self.last = frame
            self.count += 1
            self.distinct.add(hashlib.sha256(frame).hexdigest())
        out.write_bytes(b"")
        return MediaInfo(path=out)


def _clip(studio: Studio, media: Any, scene: dict[str, Any], timing: Timing, **video: Any) -> Path:
    service = RenderService(media=media, artifacts=None, catalog=studio.registry)  # type: ignore[arg-type]
    built = studio.video(scene, **video)
    parts, layer = studio.inputs(built, scene["id"])
    ctx = Ctx(job_dir=studio.root / "clip_job", cancel=Token())
    return service.clip(built, scene["id"], parts, layer, timing, ctx=ctx)


def _two_line_scene() -> dict[str, Any]:
    scene = copy.deepcopy(load("scene_full_stage.json"))
    second = copy.deepcopy(scene["lines"][0])
    second["id"] = "l_0aaaaaaaaaaaaaaaaaaaaaaaaa"
    second["display_text"] = second["speech_text"] = "둘째, 물을 끓인다."
    scene["lines"].append(second)
    scene["visual"]["elements"][0]["reveal_line_id"] = second["id"]
    return scene


@pytest.mark.parametrize(("duration_ms", "frames"), [(1000, 30), (1234, 37), (2400, 72)])
def test_12_clip_has_the_frames_of_its_timing_length(
    studio: Studio, duration_ms: int, frames: int
) -> None:
    scene = load("scene_fixed_stage.json")
    timing = timing_for(scene, speech_ms=duration_ms - 200, tail_ms=200)
    sink = FrameSink()
    _clip(studio, sink, scene, timing)
    assert frame_count(timing.duration_ms) == frames
    assert sink.count == frames


def test_29_clip_frames_come_from_the_still_drawing(studio: Studio) -> None:
    scene = load("scene_fixed_stage.json")
    sink = FrameSink()
    _clip(studio, sink, scene, timing_for(scene))
    built = studio.video(scene)
    parts, layer = studio.inputs(built, scene["id"])
    still, _ = studio.service.compose(built, scene["id"], parts, layer)
    assert sink.distinct == {hashlib.sha256(still.convert("RGB").tobytes()).hexdigest()}


def test_29_fade_scene_starts_black_and_ends_drawn(studio: Studio) -> None:
    scene = copy.deepcopy(load("scene_fixed_stage.json"))
    scene["visual"]["transition_in"] = "fade"
    sink = FrameSink()
    _clip(studio, sink, scene, timing_for(scene))
    assert sink.first == bytes(FRAME_BYTES)
    assert sink.last != sink.first


def test_29_pop_character_grows_from_nothing_with_overshoot(studio: Studio) -> None:
    scene = copy.deepcopy(load("scene_fixed_stage.json"))
    scene["visual"]["characters"][0]["motion"] = "pop"
    built = studio.video(scene)
    scales = [
        pose.figure_scale
        for pose in poses(built.scenes[scene["id"]], timing_for(scene), [20], -800)
    ]
    assert scales[0] == 0
    assert max(scales) > SCALE_STEP
    assert scales[-1] == SCALE_STEP


def test_29_move_character_slides_in_to_its_anchor(studio: Studio) -> None:
    scene = copy.deepcopy(load("scene_fixed_stage.json"))
    scene["visual"]["characters"][0]["motion"] = "move"
    built = studio.video(scene)
    offsets = [
        pose.figure_dx
        for pose in poses(built.scenes[scene["id"]], timing_for(scene), [20], -800)
    ]
    assert offsets[0] == -800
    assert offsets == sorted(offsets)
    assert offsets[-1] == 0


def test_29_bob_hops_only_while_a_line_is_spoken(studio: Studio) -> None:
    scene = copy.deepcopy(load("scene_fixed_stage.json"))
    scene["visual"]["characters"][0]["motion"] = "bob"
    built = studio.video(scene)
    timing = timing_for(scene, speech_ms=600, tail_ms=400)
    hops = [pose.figure_dy for pose in poses(built.scenes[scene["id"]], timing, [20], -800)]
    assert min(hops[:18]) < 0
    assert set(hops[19:]) == {0}


def test_29_element_pops_in_when_its_reveal_line_starts(studio: Studio) -> None:
    scene = _two_line_scene()
    built = studio.video(scene, layout="full_stage", mode="phrase", role="subject")
    timing = timing_for(scene)
    second_start = timing.lines[1].start_ms
    for index, pose in enumerate(poses(built.scenes[scene["id"]], timing, [20, 20], -800)):
        t = index * 1000 // 30
        if t < second_start:
            assert pose.elements == (None,)
        elif t >= second_start + 250:
            assert pose.elements == (SCALE_STEP,)
    sink = FrameSink()
    _clip(studio, sink, scene, timing, layout="full_stage", mode="phrase", role="subject")
    assert sink.count == frame_count(timing.duration_ms)


def test_29_long_phrase_line_renders_when_each_phrase_fits(studio: Studio) -> None:
    scene = copy.deepcopy(load("scene_full_stage.json"))
    words = ["원두를", "고르고", "물을", "끓인다"] * 15
    text = " ".join(words)
    assert len(text) > 200
    scene["lines"][0]["display_text"] = scene["lines"][0]["speech_text"] = text
    scene["lines"][0]["highlight"] = []
    spans, start = [], 0
    for index in range(0, len(words), 4):
        end = len(" ".join(words[: index + 4]))
        spans.append((start, end))
        start = end + 1
    step = 600 // len(spans)
    phrases = [
        {"start_char": a, "end_char": b, "start_ms": i * step, "end_ms": (i + 1) * step}
        for i, (a, b) in enumerate(spans)
    ]
    built = studio.video(scene, layout="full_stage", mode="phrase", role="subject")
    parts, layer = studio.inputs(built, scene["id"])
    with pytest.raises(AppError) as caught:
        studio.service.compose(built, scene["id"], parts, layer)
    assert caught.value.code == "text_overflow"
    timing = timing_for(scene, mode="phrase", phrases=[phrases])
    sink = FrameSink()
    _clip(studio, sink, scene, timing, layout="full_stage", mode="phrase", role="subject")
    assert sink.count == frame_count(timing.duration_ms)
    assert len(sink.distinct) > 1


def test_29_phrase_caption_follows_the_aligned_phrase_times() -> None:
    scene = load("scene_full_stage.json")
    text = scene["lines"][0]["display_text"]
    cut = text.index(" ") + 1
    timing = timing_for(
        scene,
        mode="phrase",
        phrases=[[
            {"start_char": 0, "end_char": cut, "start_ms": 0, "end_ms": 300},
            {"start_char": cut, "end_char": len(text), "start_ms": 300, "end_ms": 600},
        ]],
    )
    assert caption_state(timing.lines, 0, [0]).phrase == (0, cut)
    assert caption_state(timing.lines, 299, [0]).phrase == (0, cut)
    assert caption_state(timing.lines, 300, [0]).phrase == (cut, len(text))
    assert caption_state(timing.lines, 790, [0]).phrase == (cut, len(text))


def test_29_typewriter_types_whole_graphemes_only(studio: Studio) -> None:
    scene = copy.deepcopy(load("scene_dialog_stage_typewriter.json"))
    text = unicodedata.normalize("NFD", "타자효과는글자단위")
    scene["lines"][0]["display_text"] = text
    built = studio.video(scene, layout="dialog_stage", mode="typewriter")
    res = studio.service._resolve(built)
    block = fit(res.font, text, None, width=900, height=400, max_lines=2,
                sizes=res.font.sizes(96, 24), where="test")
    total = sum(len(line.units) for line in block.lines)
    spans = clusters(text)
    assert len(spans) == total
    phrases = [
        {
            "start_char": start,
            "end_char": end,
            "start_ms": index * 600 // len(spans),
            "end_ms": (index + 1) * 600 // len(spans),
        }
        for index, (start, end) in enumerate(spans)
    ]
    timing = timing_for(scene, mode="typewriter", phrases=[phrases])
    typed = [caption_state(timing.lines, t, [total]).typed for t in range(0, 801, 10)]
    assert typed[0] == 1 and typed[-1] == total
    assert typed == sorted(typed)
    for index, phrase in enumerate(phrases):
        shown = caption_state(timing.lines, phrase["start_ms"], [total]).typed
        assert shown == index + 1
    glyphs = [unit.text for unit in units(text) if not unit.space]
    for count in range(total + 1):
        shown = [
            unit.text for line in _typed(block, count).lines for unit in line.units
            if not unit.space
        ]
        assert shown == glyphs[: len(shown)]
        assert not any(0x1100 <= ord(char) <= 0x11FF for glyph in shown for char in glyph)
    sink = FrameSink()
    _clip(studio, sink, scene, timing, layout="dialog_stage", mode="typewriter")
    assert len(sink.distinct) > 2


@ffmpeg.requires_ffmpeg
def test_12_encoded_clip_matches_timing_length_and_has_no_sound(studio: Studio) -> None:
    scene = load("scene_fixed_stage.json")
    timing = timing_for(scene, speech_ms=1034, tail_ms=200)
    path = _clip(studio, ffmpeg.adapter(), scene, timing)
    info = ffmpeg.adapter().probe(path)
    assert (info.width, info.height, info.fps) == (1080, 1920, 30)
    assert info.sample_rate is None
    assert len(ffmpeg.video_packets(path)) == frame_count(timing.duration_ms)
    assert info.duration_ms is not None
    assert abs(info.duration_ms - timing.duration_ms) <= 1000 // 30 // 2 + 1
