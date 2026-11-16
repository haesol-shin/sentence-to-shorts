"""Frame timeline of a scene clip: frame count, motion and caption state per frame.

Every value here is a pure function of the scene, its timing artifact and the
frame time, so the same inputs give the same frames. The renderer draws a pose;
this module only decides which pose a frame shows.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

from app.ports import AppError
from app.schemas.artifact import Timing, TimingLine
from app.schemas.common import CaptionMode
from app.schemas.scene import Scene, SceneMotion, TransitionIn

FPS = 30
"""Output frame rate (CONTRACTS 12)."""

POP_MS = 400
"""Length of the character pop, from nothing to a short overshoot and back to rest."""

ELEMENT_POP_MS = 250
"""Length of an element's pop when its reveal line starts."""

BOB_PERIOD_MS = 600
"""One hop of the bob motion while a line is spoken."""

BOB_PX = 24
"""Height of a bob hop on the 1080x1920 frame."""

MOVE_MS = 500
"""Length of the slide-in of the move motion."""

FADE_MS = 300
"""Length of the in-scene fade from black."""

SCALE_STEP = 50
"""Scales are kept as multiples of 1/50, so nearby frames reuse one resized image."""

OPAQUE = 255


def frame_count(duration_ms: int) -> int:
    """Frames of a clip of ``duration_ms``, rounded to the nearest frame.

    The sound and assemble services place scenes with the same rule, so the
    audio and the subtitles stay on the frames the clips really have.
    """
    return max(1, (duration_ms * FPS + 500) // 1000)


def frame_time_ms(index: int) -> int:
    return index * 1000 // FPS


@dataclass(frozen=True)
class CaptionState:
    """What the caption box shows: a whole line, one phrase of it, or a typed prefix."""

    line: int
    phrase: tuple[int, int] | None = None
    typed: int | None = None


@dataclass(frozen=True)
class Pose:
    """One frame's drawing state. Scales are in 1/``SCALE_STEP``; ``None`` hides an element."""

    figure_scale: int
    figure_dx: int
    figure_dy: int
    elements: tuple[int | None, ...]
    caption: CaptionState
    fade: int


def rest_pose(scene: Scene) -> Pose:
    """The still's pose: everything shown at rest and the first line's full caption."""
    assert scene.visual is not None
    return Pose(
        figure_scale=SCALE_STEP,
        figure_dx=0,
        figure_dy=0,
        elements=tuple(SCALE_STEP for _ in scene.visual.elements),
        caption=CaptionState(line=0),
        fade=OPAQUE,
    )


def _pop_scale(elapsed_ms: int, length_ms: int) -> int:
    """Ease-out-back from 0 to 1 with a short overshoot, in 1/``SCALE_STEP``."""
    if elapsed_ms >= length_ms:
        return SCALE_STEP
    progress = max(0.0, elapsed_ms / length_ms) - 1.0
    value = 1.0 + 2.70158 * progress**3 + 1.70158 * progress**2
    return max(0, round(value * SCALE_STEP))


def _speaking(lines: list[TimingLine], t: int) -> TimingLine | None:
    for line in lines:
        if line.start_ms <= t < line.start_ms + line.speech_ms:
            return line
    return None


def _figure(motion: SceneMotion, t: int, lines: list[TimingLine], travel: int) -> tuple[
    int, int, int
]:
    if motion == SceneMotion.pop:
        return _pop_scale(t, POP_MS), 0, 0
    if motion == SceneMotion.bob:
        line = _speaking(lines, t)
        if line is None:
            return SCALE_STEP, 0, 0
        hop = abs(math.sin(math.pi * (t - line.start_ms) / BOB_PERIOD_MS))
        return SCALE_STEP, 0, -round(BOB_PX * hop)
    if motion == SceneMotion.move and t < MOVE_MS:
        eased = 1.0 - (1.0 - t / MOVE_MS) ** 3
        return SCALE_STEP, round((1.0 - eased) * travel), 0
    return SCALE_STEP, 0, 0


def _active(lines: list[TimingLine], t: int) -> int:
    """The last line that has started; before the first start, the first line."""
    active = 0
    for index, line in enumerate(lines):
        if line.start_ms <= t:
            active = index
    return active


def caption_state(lines: list[TimingLine], t: int, typed_units: list[int]) -> CaptionState:
    """Caption of the frame at ``t``. A line stays on screen until the next one starts.

    Phrase captions show the last phrase that has started. A typewriter line shows
    the clusters whose timing span has started and keeps them to the line end;
    ``typed_units`` is each line's grapheme count as laid out.
    """
    index = _active(lines, t)
    line = lines[index]
    mode = line.caption.mode_used
    if mode == CaptionMode.phrase and line.caption.phrases:
        current = line.caption.phrases[0]
        for phrase in line.caption.phrases:
            if phrase.start_ms <= t:
                current = phrase
        return CaptionState(line=index, phrase=(current.start_char, current.end_char))
    if mode == CaptionMode.typewriter:
        total = typed_units[index]
        typed = sum(1 for phrase in line.caption.phrases if phrase.start_ms <= t)
        return CaptionState(line=index, typed=min(total, typed))
    return CaptionState(line=index)


def poses(
    scene: Scene, timing: Timing, typed_units: list[int], travel: int
) -> Iterator[Pose]:
    """One pose per frame of the clip. ``travel`` is the move motion's start offset."""
    assert scene.visual is not None
    visual = scene.visual
    lines = timing.lines
    starts = {line.line_id: line.start_ms for line in lines}
    reveals: list[int] = []
    for element in visual.elements:
        if element.reveal_line_id is None:
            reveals.append(-1)
        elif element.reveal_line_id in starts:
            reveals.append(starts[element.reveal_line_id])
        else:
            raise AppError("reveal_line_unknown", detail={"element": element.id})
    motion = visual.characters[0].motion if visual.characters else SceneMotion.none
    fade = visual.transition_in == TransitionIn.fade
    for index in range(frame_count(timing.duration_ms)):
        t = frame_time_ms(index)
        scale, dx, dy = _figure(motion, t, lines, travel)
        elements = tuple(
            SCALE_STEP if start < 0
            else (None if t < start else _pop_scale(t - start, ELEMENT_POP_MS))
            for start in reveals
        )
        yield Pose(
            figure_scale=scale,
            figure_dx=dx,
            figure_dy=dy,
            elements=elements,
            caption=caption_state(lines, t, typed_units),
            fade=min(OPAQUE, t * OPAQUE // FADE_MS) if fade else OPAQUE,
        )


__all__ = [
    "FPS",
    "CaptionState",
    "Pose",
    "caption_state",
    "frame_count",
    "frame_time_ms",
    "poses",
    "rest_pose",
]
