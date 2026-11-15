"""A forced stop during generate: the same job resumes and keeps the finished clips."""

from __future__ import annotations

from pathlib import Path

from tests.e2e.support import Api, Server, Studio, probe, stage, wait_until
from tests.media.ffmpeg import requires_ffmpeg

pytestmark = requires_ffmpeg

CLIPS_BEFORE_STOP = 2


def test_27_killed_server_resumes_the_job_and_reuses_the_finished_clips(
    tmp_path: Path,
) -> None:
    server = Server(tmp_path)
    server.start(stall_after_clips=CLIPS_BEFORE_STOP)
    api = Api(server)
    try:
        studio = Studio(api)
        video = studio.ready_to_generate()
        scene_order = list(video["scene_order"])
        job = studio.start_generate(video)
        wait_until(server.stall_ready.is_file, timeout_s=120, what="two clips to be rendered")
        assert api.get(f"/jobs/{job['id']}")["state"] == "running"
    finally:
        api.close()
        server.kill()

    server.start()
    api = Api(server)
    try:
        studio = Studio(api)
        finished = api.wait_job(job)
        assert finished["id"] == job["id"]
        assert finished["attempt"] == 2
        clips = stage(finished, "clip")
        assert clips["cache_hits"] == CLIPS_BEFORE_STOP
        assert clips["rebuilt_scene_ids"] == scene_order[CLIPS_BEFORE_STOP:]
        assert finished["result"]["rebuilt_scene_ids"] == scene_order[CLIPS_BEFORE_STOP:]
        target = tmp_path / "resumed.mp4"
        target.write_bytes(api.download(f"/videos/{video['id']}/download/mp4"))
        found = probe(target)
        assert (found["width"], found["height"], found["fps"]) == (1080, 1920, 30)
        assert studio.head(video["id"])["revision"] == video["revision"]
    finally:
        api.close()
        server.kill()
