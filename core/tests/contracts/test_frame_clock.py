"""One frame clock for scene video, audio and subtitles."""

from __future__ import annotations

import pytest

from app.ports import frame_count, scene_starts_ms
from app.schemas.artifact import Timing
from tests.conftest import load_json


@pytest.mark.parametrize(
    ("duration_ms", "frames"),
    [(0, 1), (1, 1), (16, 1), (17, 1), (49, 1), (50, 2), (51, 2), (1011, 30)],
)
def test_12_frame_count_keeps_one_frame_and_rounds_half_up(
    duration_ms: int, frames: int,
) -> None:
    assert frame_count(duration_ms) == frames


@pytest.mark.parametrize(
    ("durations", "starts", "total_ms"),
    [([], [], 0), ([1, 1, 1], [0, 33, 67], 100),
     ([1011, 17, 50], [0, 1000, 1033], 1100)],
)
def test_12_scene_clock_converts_accumulated_frames(
    durations: list[int], starts: list[int], total_ms: int,
) -> None:
    timing = Timing.model_validate(load_json("contracts/valid/timing_sentence_fallback.json"))
    scenes = [timing.model_copy(update={"duration_ms": duration}) for duration in durations]
    assert scene_starts_ms(scenes) == (starts, total_ms)
