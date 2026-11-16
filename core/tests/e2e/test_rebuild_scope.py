"""What a generate rebuilds after one kind of edit, read from the job's stage records."""

from __future__ import annotations

from typing import Any

from tests.e2e.support import Studio, stage
from tests.media.ffmpeg import requires_ffmpeg

pytestmark = requires_ffmpeg


def _generated(studio: Studio) -> tuple[dict[str, Any], dict[str, Any]]:
    video = studio.ready_to_generate()
    return video, studio.generate(video)


def _set_lines(video: dict[str, Any], scene_id: str, **changes: str) -> dict[str, Any]:
    lines = [{**line, **changes} for line in video["scenes"][scene_id]["lines"]]
    return {
        "op": "set",
        "path": f"/scenes/{scene_id}/lines",
        "value": lines,
        "origin": "user",
    }


def test_12_reorder_rebuilds_no_scene_clip(studio: Studio) -> None:
    video, first = _generated(studio)
    order = list(video["scene_order"])
    swapped = [order[1], order[0], *order[2:]]

    video = studio.apply_change(video, [{"op": "reorder", "order": swapped}])
    assert video["scene_order"] == swapped
    second = studio.generate(video)

    assert stage(second, "clip")["rebuilt_scene_ids"] == []
    assert second["result"]["artifacts"]["clip"] == first["result"]["artifacts"]["clip"]
    assert stage(second, "tts")["rebuilt_scene_ids"] == []
    assert second["result"]["artifacts"]["final"] != first["result"]["artifacts"]["final"]


def test_12_bgm_change_rebuilds_no_scene_clip(studio: Studio) -> None:
    video, first = _generated(studio)
    current = video["settings"]["audio"]["bgm"]["entry"]["id"]
    tracks = studio.api.get("/catalog/bgm", limit=50)["items"]
    other = next(item for item in tracks if item["origin"] == "builtin" and item["id"] != current)

    video = studio.apply_change(
        video,
        [
            {
                "op": "set",
                "path": "/settings/audio/bgm/entry",
                "value": {"id": other["id"], "revision": other["revision"]},
                "origin": "user",
            }
        ],
    )
    second = studio.generate(video)

    assert stage(second, "clip")["rebuilt_scene_ids"] == []
    assert second["result"]["artifacts"]["clip"] == first["result"]["artifacts"]["clip"]
    assert stage(second, "mix")["state"] == "done"
    assert second["result"]["artifacts"]["mix"] != first["result"]["artifacts"]["mix"]


def test_11_display_text_edit_keeps_the_voice_and_speech_edit_redoes_one_line(
    studio: Studio,
) -> None:
    video, _ = _generated(studio)
    target = video["scene_order"][1]
    line_count = sum(len(scene["lines"]) for scene in video["scenes"].values())

    video = studio.apply_change(
        video, [_set_lines(video, target, display_text="화면 글만 바꿨어요")]
    )
    shown = studio.generate(video)
    assert stage(shown, "tts")["rebuilt_scene_ids"] == []
    assert stage(shown, "tts")["cache_hits"] == line_count

    video = studio.apply_change(
        video, [_set_lines(video, target, speech_text="읽는 글만 바꿨어요")]
    )
    spoken = studio.generate(video)
    assert stage(spoken, "tts")["rebuilt_scene_ids"] == [target]
    assert stage(spoken, "tts")["cache_hits"] == line_count - 1
