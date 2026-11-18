"""Still rendering helpers over the real builtin registry and contract fixtures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.plugins.registry import Registry
from app.schemas.artifact import Timing
from app.schemas.video import Video
from app.services.render import BuiltinLayerDrawer, PixelPartsBuilder, RenderService

VALID = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "valid"


class Token:
    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


@dataclass
class Ctx:
    job_dir: Path
    cancel: Token


def load(name: str) -> dict[str, Any]:
    return json.loads((VALID / name).read_text(encoding="utf-8"))


@dataclass
class Studio:
    registry: Registry
    service: RenderService
    parts: PixelPartsBuilder
    layers: BuiltinLayerDrawer
    root: Path

    def video(
        self,
        scene: dict[str, Any] | None = None,
        *,
        layout: str = "fixed_stage",
        mode: str = "sentence",
        theme: str = "day",
        role: str = "presenter",
        position: str = "bottom",
        base: str = "video_ko_just_three.json",
    ) -> Video:
        raw = load(base)
        settings = raw["settings"]
        settings["visual"]["theme_id"] = theme
        settings["format"]["layout"] = self.registry.pin("template", layout).model_dump()
        settings["format"]["character_role"] = role
        settings["caption"]["mode"] = mode
        settings["caption"]["position"] = position
        if scene is not None:
            raw["scenes"] = {scene["id"]: scene}
            raw["scene_order"] = [scene["id"]]
        return Video.model_validate(raw)

    def inputs(self, video: Video, scene_id: str) -> tuple[dict[str, bytes], bytes | None]:
        scene = video.scenes[scene_id]
        assert scene.visual is not None
        style = video.settings.visual.art_style
        parts: dict[str, bytes] = {}
        if scene.visual.characters:
            placement = scene.visual.characters[0]
            parts = self.parts.build_parts(
                style,
                video.settings.visual.character,
                placement.expression_id,
                placement.pose_id,
                0,
                cancel=Token(),
            )
        skin = self.parts.theme_parts(style, video.settings.visual.theme_id)
        layer, _ = self.layers.draw_layer(
            video.settings.format.layout, scene, (1080, 1920), {**parts, **skin}, 0,
            cancel=Token(),
        )
        return parts, layer

    def still(
        self, video: Video, scene_id: str, timing: Timing | None = None, *, name: str = "job"
    ) -> Path:
        parts, layer = self.inputs(video, scene_id)
        ctx = Ctx(job_dir=self.root / name, cancel=Token())
        return self.service.still(video, scene_id, parts, layer, timing, ctx=ctx)


@pytest.fixture(scope="session")
def registry() -> Registry:
    registry = Registry()
    registry.load()
    return registry


@pytest.fixture
def studio(registry: Registry, tmp_path: Path) -> Studio:
    return Studio(
        registry=registry,
        service=RenderService(media=None, artifacts=None, catalog=registry),  # type: ignore[arg-type]
        parts=PixelPartsBuilder(registry),
        layers=BuiltinLayerDrawer(registry),
        root=tmp_path,
    )

