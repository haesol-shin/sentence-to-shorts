"""Change plan construction is owned by the pipeline."""

from __future__ import annotations

from app.schemas.change import ChangePlan, Op, Target
from app.schemas.video import Video, VideoBuild
from app.services.pipeline.types import Services


def plan_change(
    video: Video,
    ops: list[Op],
    source: str,
    target: Target,
    services: Services,
) -> ChangePlan:
    raise NotImplementedError


def build_view(video: Video, services: Services) -> VideoBuild:
    raise NotImplementedError


__all__ = ["build_view", "plan_change"]
