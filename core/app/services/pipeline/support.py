"""Small job kinds that do not change the video plan."""

from __future__ import annotations

from app.ports import JobContext
from app.schemas.job import Job
from app.schemas.video import VideoStage
from app.services.pipeline.build import load_video, require_stage
from app.services.pipeline.run_state import check_context
from app.services.pipeline.types import Services


def run_precheck(job: Job, ctx: JobContext, services: Services) -> dict[str, object]:
    video = load_video(job, services)
    require_stage(video, VideoStage.scenes_confirmed, "scenes_not_confirmed")
    check_context(video, ctx, services)
    report = services.story.precheck(video, ctx=ctx)
    check_context(video, ctx, services)
    return {"precheck": report.model_dump(mode="json")}


__all__ = ["run_precheck"]
