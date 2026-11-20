"""Story service contract: draft, script, scene data, chat and precheck."""

from __future__ import annotations

from app.ports import (
    AppSettings,
    CatalogPort,
    JobContext,
    LlmPort,
    Proposal,
    ServiceDeps,
)
from app.schemas.api import PrecheckReport
from app.schemas.change import Op, Target
from app.schemas.video import Video


class StoryService:
    def __init__(self, llm: LlmPort, catalog: CatalogPort) -> None:
        self.llm = llm
        self.catalog = catalog

    def draft(
        self,
        video: Video,
        message: str,
        card_id: str | None,
        *,
        ctx: JobContext,
    ) -> list[Op]:
        raise NotImplementedError

    def write_script(self, video: Video, *, ctx: JobContext) -> list[Op]:
        """Run the script and split routes; the caller applies the returned ops."""
        raise NotImplementedError

    def scene_data(
        self, video: Video, scene_ids: list[str], *, ctx: JobContext
    ) -> list[Op]:
        raise NotImplementedError

    def interpret(
        self, video: Video, text: str, target: Target, *, ctx: JobContext
    ) -> Proposal:
        raise NotImplementedError

    def rewrite_scene(
        self, video: Video, scene_id: str, instruction: str, *, ctx: JobContext
    ) -> Proposal:
        """Change one scene; the proposal carries what the scene route cannot do."""
        raise NotImplementedError

    def precheck(self, video: Video, *, ctx: JobContext) -> PrecheckReport:
        raise NotImplementedError


def create(settings: AppSettings, deps: ServiceDeps) -> StoryService:
    return StoryService(deps.llm, deps.catalog)


__all__ = ["StoryService", "create"]
