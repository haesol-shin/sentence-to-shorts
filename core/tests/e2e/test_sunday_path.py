"""The Sunday acceptance path over HTTP: a real server process, real Pillow and ffmpeg.

One sentence becomes a draft, the script and the scenes are confirmed, the video
is generated, one scene is rewritten and undone, and a next video starts from it.
The language model answers from recordings and the voice is the fixed tone engine, so this
proves the wiring of the whole path and says nothing about generated quality.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from PIL import Image

from tests.e2e.support import Server, Studio, probe, sha256_of
from tests.media.ffmpeg import requires_ffmpeg

pytestmark = requires_ffmpeg

# The rewrite recorded under fixtures/llm/scene_rewrite.
REWRITTEN_LINE = "핵심만 기억해요"


def _lines(video: dict[str, Any], scene_id: str) -> list[str]:
    return [line["display_text"] for line in video["scenes"][scene_id]["lines"]]


def _clip_digests(studio: Studio, job: dict[str, Any]) -> dict[str, str]:
    """SHA-256 of every scene clip file a finished generate job produced."""
    return {
        scene_id: sha256_of(studio.api.download(f"/artifacts/{artifact_id}"))
        for scene_id, artifact_id in job["result"]["artifacts"]["clip"].items()
    }


def _revision_files(server: Server, project_id: str, video_id: str) -> dict[str, str]:
    root = server.data_dir / "p" / project_id / "v" / video_id / "r"
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.glob("*.json"))
    }


def _assert_mp4(studio: Studio, video_id: str, target: Path) -> dict[str, Any]:
    target.write_bytes(studio.api.download(f"/videos/{video_id}/download/mp4"))
    found = probe(target)
    assert (found["width"], found["height"], found["fps"]) == (1080, 1920, 30)
    assert found["sample_rate"] > 0
    expected_ms = studio.api.get(f"/videos/{video_id}")["build"]["actual_ms"]
    assert expected_ms is not None
    assert abs(found["duration_ms"] - expected_ms) <= 300
    return found


def test_1_sunday_path_from_one_sentence_to_a_next_video(
    studio: Studio, server: Server, tmp_path: Path
) -> None:
    api = studio.api
    video = studio.draft(studio.new_video())
    video_id, project_id = video["id"], video["project_id"]
    scene_order = list(video["scene_order"])
    assert video["stage"] == "draft"
    assert video["topic"] and video["script"] is not None
    assert len(scene_order) == 5

    # Criterion 2: no scene preview before the script is confirmed.
    refused = api.post(
        f"/videos/{video_id}/previews", {"base_revision": video["revision"]}, expect=409
    )
    assert refused["code"] == "script_not_confirmed"
    assert [job["kind"] for job in api.get("/jobs", video_id=video_id)["items"]] == ["draft"]
    build = api.get(f"/videos/{video_id}")["build"]
    assert all(scene["still"]["state"] != "fresh" for scene in build["scenes"].values())

    video = studio.confirm(video, "concept/confirm")
    video = studio.confirm(video, "script/confirm")
    assert video["stage"] == "script_confirmed"
    video = studio.preview(video)
    build = api.get(f"/videos/{video_id}")["build"]
    for scene in build["scenes"].values():
        assert scene["still"]["state"] == "fresh"
    still = api.download(f"/artifacts/{build['scenes'][scene_order[0]]['still']['artifact']['id']}")
    assert Image.open(io.BytesIO(still)).size == (540, 960)

    video = studio.confirm(video, "scenes/confirm")
    assert video["stage"] == "scenes_confirmed"
    first = studio.generate(video)
    _assert_mp4(studio, video_id, tmp_path / "first.mp4")
    first_clips = _clip_digests(studio, first)
    first_final = first["result"]["artifacts"]["final"]
    assert set(first_clips) == set(scene_order)

    # Criteria 10 and 26: one scene is rewritten by chat, compared, then applied.
    target = scene_order[2]
    original_lines = _lines(video, target)
    message = api.post(
        f"/videos/{video_id}/messages",
        {
            "base_revision": video["revision"],
            "text": "",
            "target": {"scene_id": target, "pointer": None},
        },
        expect=202,
    )
    plan_id = api.wait_job(message)["result"]["change_id"]
    plan = api.get(f"/changes/{plan_id}")
    assert plan["status"] == "proposed" and plan["requires_confirmation"]
    assert plan["effects"]["scene_ids_tts"] == [target]
    assert plan["effects"]["scene_ids_render"] == [target]
    assert _lines(video, target) == original_lines
    api.post(f"/changes/{plan_id}/apply", {"base_revision": video["revision"]})
    video = studio.head(video_id)
    assert _lines(video, target) == [REWRITTEN_LINE]

    second = studio.generate(video)
    assert second["result"]["rebuilt_scene_ids"] == [target]
    second_clips = _clip_digests(studio, second)
    for scene_id in scene_order:
        if scene_id == target:
            assert second_clips[scene_id] != first_clips[scene_id]
        else:
            assert second_clips[scene_id] == first_clips[scene_id]
    assert second["result"]["artifacts"]["final"] != first_final
    _assert_mp4(studio, video_id, tmp_path / "second.mp4")

    # Criterion 26: undo brings the earlier script and the earlier final video back.
    api.post(f"/videos/{video_id}/undo", {"base_revision": video["revision"]})
    video = studio.head(video_id)
    assert _lines(video, target) == original_lines
    restored = api.get(f"/videos/{video_id}")["build"]["final"]
    assert restored["state"] == "fresh"
    assert restored["artifact"]["id"] == first_final

    # Criterion 25: the next video keeps the settings and starts with no topic or script.
    before = _revision_files(server, project_id, video_id)
    assert before
    following = api.post(
        f"/projects/{project_id}/videos", {"from_video_id": video_id, "preset_id": None}, expect=201
    )
    assert following["id"] != video_id
    assert following["topic"] == "" and following["script"] is None
    assert following["scene_order"] == [] and following["scenes"] == {}
    # The format, the art style, the character and the voice carry over. The theme and the
    # BGM are varied items, so a next video may pick others.
    kept = following["settings"]
    assert kept["format"] == video["settings"]["format"]
    for key in ("art_style", "character"):
        assert kept["visual"][key] == video["settings"]["visual"][key]
    assert kept["audio"]["voice"] == video["settings"]["audio"]["voice"]
    assert _revision_files(server, project_id, video_id) == before
    kinds = {job["kind"] for job in api.get("/jobs", limit=50)["items"]}
    assert not kinds & {"style", "template", "bgm_code"}
    assert api.get("/jobs", video_id=following["id"])["items"] == []
