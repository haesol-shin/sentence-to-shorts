"""Job execution: the only place that owns step order."""

from __future__ import annotations

from app.ports import AppError, JobContext
from app.schemas.job import Job, JobKind
from app.services.pipeline import build, changes, support
from app.services.pipeline.types import Services

CHANGE_KINDS = frozenset(
    {JobKind.draft, JobKind.script, JobKind.chat, JobKind.style, JobKind.template}
)


def run(job: Job, ctx: JobContext, services: Services) -> dict[str, object]:
    if job.kind is JobKind.preview:
        return build.run_preview(job, ctx, services)
    if job.kind is JobKind.generate:
        return build.run_generate(job, ctx, services)
    if job.kind in CHANGE_KINDS:
        return changes.run_change_job(job, ctx, services)
    if job.kind is JobKind.reference:
        return changes.run_reference_job(job, ctx, services)
    if job.kind is JobKind.precheck:
        return support.run_precheck(job, ctx, services)
    if job.kind is JobKind.bgm_code:
        return changes.run_bgm_code(ctx.input, ctx, services)
    if job.kind is JobKind.bgm_upload:
        return changes.run_bgm_upload(ctx.input, ctx, services)
    raise AppError("not_implemented", detail={"kind": job.kind.value})


__all__ = ["run"]
