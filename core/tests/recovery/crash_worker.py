"""A server process for the forced-stop tests.

Usage: python -m tests.recovery.crash_worker <root> <ready file>

It starts the runner on the isolated roots. The job publishes one clip per scene,
records a checkpoint and holds the clip for the video, then writes the ready file
after the first scene and blocks until the test kills the process.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

from app.jobs import LocalJobContext
from app.schemas.job import Checkpoint, Job, Stage
from tests.jobs.support import open_env, publish_clip


def clip_bytes(scene_id: str) -> bytes:
    return f"clip of {scene_id}".encode()


def main(root: Path, ready: Path) -> None:
    env = open_env(root)

    def run_job(job: Job, ctx: LocalJobContext) -> dict[str, Any]:
        for scene_id in ctx.input["scenes"]:
            with ctx.stage(Stage.clip):
                artifact = publish_clip(env.artifacts, ctx.job_dir, clip_bytes(scene_id), job.id)
                env.artifacts.hold([artifact.id], f"rev:{job.video_id}:1")
                ctx.checkpoint(
                    Checkpoint(
                        stage=Stage.clip,
                        scene_id=scene_id,
                        line_id=None,
                        artifact_id=artifact.id,
                        digest=artifact.digest,
                    )
                )
            staged = ready.with_name(ready.name + ".tmp")
            staged.write_text(artifact.id, encoding="utf-8")
            staged.replace(ready)
            threading.Event().wait()
        return {}

    env.runner(run_job).start()
    threading.Event().wait()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
