"""Job execution: the only place that owns step order."""

from __future__ import annotations

from app.ports import JobContext
from app.schemas.job import Job
from app.services.pipeline.types import Services


def run(job: Job, ctx: JobContext, services: Services) -> dict[str, object]:
    raise NotImplementedError


__all__ = ["run"]
