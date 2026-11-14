"""Generated style, template and BGM package contract."""

from __future__ import annotations

from app.ports import (
    AppSettings,
    CatalogPort,
    JobContext,
    LayerDrawer,
    LlmPort,
    PartsBuilder,
    SandboxPort,
    ServiceDeps,
)
from app.schemas.api import BgmCodeRequest, StyleRequest, TemplateRequest
from app.schemas.common import PinnedRef
from app.schemas.video import Video


class TemplatesService:
    def __init__(
        self, llm: LlmPort, sandbox: SandboxPort, catalog: CatalogPort
    ) -> None:
        self.llm = llm
        self.sandbox = sandbox
        self.catalog = catalog

    def generate_style(
        self,
        req: StyleRequest,
        video: Video,
        hints: dict[str, object] | None,
        *,
        ctx: JobContext,
    ) -> PinnedRef:
        raise NotImplementedError

    def generate_template(
        self, req: TemplateRequest, video: Video, *, ctx: JobContext
    ) -> PinnedRef:
        raise NotImplementedError

    def generate_bgm(self, req: BgmCodeRequest, *, ctx: JobContext) -> PinnedRef:
        raise NotImplementedError

    def parts_builder(self, style: PinnedRef) -> PartsBuilder:
        raise NotImplementedError

    def layer_drawer(self, template: PinnedRef) -> LayerDrawer:
        raise NotImplementedError


def create(settings: AppSettings, deps: ServiceDeps) -> TemplatesService:
    return TemplatesService(deps.llm, deps.sandbox, deps.catalog)


__all__ = ["TemplatesService", "create"]
