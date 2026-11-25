"""Built-in flat and cutout styles: manifests, stored assets and the render dispatch."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.plugins.registry import Registry
from app.schemas.style_manifest import RenderScale, StyleManifest
from app.schemas.video import Video
from app.services.render import (
    BUILTIN_LAYER_DRAWERS,
    BUILTIN_PARTS_BUILDERS,
    RenderService,
)
from app.services.render.sprites import load_sprite, rasterize
from app.services.templates.service import TemplatesService

STYLES = ("flat", "cutout")
LABELS = {"flat": ("플랫", "Flat"), "cutout": ("컷아웃", "Cutout")}
CANDIDATE = {
    "preset_id": None,
    "slots": {
        "body": "body_hero",
        "face": "face_neutral",
        "hair": "hair_short",
        "hat": None,
        "outfit": None,
        "prop": None,
    },
}
CAPTION = "첫 번째는 물의 온도예요"
VALID = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "valid"
LAYOUT = "fixed_stage"


class Token:
    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


class NoSandbox:
    """The built-in packages store every asset, so a render never reaches the sandbox."""

    def run(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("the render ran generated code")

    def runtime_digest(self) -> str:
        raise AssertionError("the render read the sandbox runtime")


@pytest.fixture(scope="module")
def registry() -> Registry:
    registry = Registry()
    registry.load()
    return registry


def _manifest(registry: Registry, style_id: str) -> StyleManifest:
    manifest = registry.get("art_style", style_id)
    assert isinstance(manifest, StyleManifest)
    return manifest


def _character(**slots: str | None) -> dict[str, Any]:
    """The candidate character with the given slots replaced."""
    character = {**CANDIDATE, "slots": dict(CANDIDATE["slots"])}
    character["slots"].update(slots)
    return character


def _video(
    registry: Registry,
    style_id: str,
    *,
    background: str,
    theme: str,
    character: dict[str, Any],
    expression: str = "expr_happy",
    pose: str = "pose_wave",
    with_icon: bool = False,
) -> tuple[Video, str]:
    raw = json.loads((VALID / "video_ko_just_three.json").read_text(encoding="utf-8"))
    settings = raw["settings"]
    settings["visual"]["art_style"] = registry.pin("art_style", style_id).model_dump()
    settings["visual"]["theme_id"] = theme
    settings["visual"]["character"] = character
    settings["format"]["layout"] = registry.pin("template", LAYOUT).model_dump()
    settings["format"]["character_role"] = "presenter"
    settings["caption"]["mode"] = "sentence"
    settings["caption"]["position"] = "bottom"
    scene_id = raw["scene_order"][0]
    scene = raw["scenes"][scene_id]
    scene["visual"]["background_id"] = background
    scene["visual"]["characters"] = [
        {
            "anchor": "center",
            "expression_id": expression,
            "pose_id": pose,
            "motion": "none",
        }
    ]
    line = scene["lines"][0]
    line["display_text"] = CAPTION
    line["speech_text"] = CAPTION
    line["highlight"] = []
    if with_icon:
        scene["visual"]["elements"] = [
            {
                "id": "e_0wyybe1tnp8fktk2g80mbghwh9",
                "kind": "asset",
                "value": "icon_arrow",
                "anchor": "top",
                "reveal_line_id": None,
            }
        ]
    return Video.model_validate(raw), scene_id


def _compose(
    registry: Registry,
    style_id: str,
    *,
    background: str,
    theme: str,
    character: dict[str, Any],
    expression: str = "expr_happy",
    pose: str = "pose_wave",
    with_icon: bool = False,
) -> tuple[Image.Image, dict[str, Any], dict[str, bytes]]:
    templates = TemplatesService(
        None,  # type: ignore[arg-type]
        NoSandbox(),  # type: ignore[arg-type]
        registry,
        builtin_parts=BUILTIN_PARTS_BUILDERS,
        builtin_layers=BUILTIN_LAYER_DRAWERS,
    )
    style = registry.pin("art_style", style_id)
    builder = templates.parts_builder(style)
    parts = builder.build_parts(
        style, character, expression, pose, 0, cancel=Token()
    )
    parts.update(builder.theme_parts(style, theme))
    video, scene_id = _video(
        registry,
        style_id,
        background=background,
        theme=theme,
        character=character,
        expression=expression,
        pose=pose,
        with_icon=with_icon,
    )
    scene = video.scenes[scene_id]
    drawer = templates.layer_drawer(video.settings.format.layout)
    layer, _ = drawer.draw_layer(
        video.settings.format.layout, scene, (1080, 1920), parts, 0, cancel=Token()
    )
    frame, record = RenderService(None, None, registry).compose(  # type: ignore[arg-type]
        video, scene_id, parts, layer
    )
    return frame, record, parts


def test_6_default_styles_share_the_pixel_rig_and_themes(registry: Registry) -> None:
    pixel = _manifest(registry, "pixel")
    pixel_assets = {asset.id for asset in pixel.assets}
    for style_id in STYLES:
        manifest = _manifest(registry, style_id)
        assert manifest.origin.value == "builtin"
        assert manifest.status.value == "ready"
        assert (manifest.label.ko, manifest.label.en) == LABELS[style_id]
        assert manifest.canvas.scale is RenderScale.smooth
        assert manifest.rig.slots.model_dump() == pixel.rig.slots.model_dump()
        assert manifest.rig.expressions == pixel.rig.expressions
        assert manifest.rig.poses == pixel.rig.poses
        assert [theme.id for theme in manifest.themes] == [theme.id for theme in pixel.themes]
        for theme, pixel_theme in zip(manifest.themes, pixel.themes, strict=True):
            assert theme.backgrounds == pixel_theme.backgrounds
            assert theme.skin_id == pixel_theme.skin_id
        assert manifest.capabilities.model_dump() == pixel.capabilities.model_dump()
        assert {asset.id for asset in manifest.assets} == pixel_assets


@pytest.mark.parametrize("style_id", STYLES)
def test_6_default_style_stores_every_asset_as_a_readable_grid(
    registry: Registry, style_id: str
) -> None:
    manifest = _manifest(registry, style_id)
    root = registry.package_dir("art_style", registry.pin("art_style", style_id))
    for asset in manifest.assets:
        image = rasterize(load_sprite(root / asset.file, asset.id))
        assert image.getbbox() is not None, asset.id


def test_6_catalog_lists_the_default_styles(client: TestClient) -> None:
    listing = client.get("/api/v1/catalog/art_style")
    assert listing.status_code == 200
    assert set(STYLES) <= {item["id"] for item in listing.json()["items"]}
    for style_id in STYLES:
        response = client.get(f"/api/v1/catalog/art_style/{style_id}")
        assert response.status_code == 200
        manifest = response.json()
        assert manifest["renderer"]["kind"] == "sandbox"
        assert len(manifest["assets"]) == 30


@pytest.mark.parametrize("style_id", STYLES)
@pytest.mark.parametrize(
    ("expression", "pose", "slots"),
    [
        ("expr_happy", "pose_wave", {}),
        ("expr_surprised", "pose_idle", {}),
        ("expr_happy", "pose_wave", {"body": "body_round"}),
        ("expr_happy", "pose_wave", {"face": "face_glasses"}),
        ("expr_happy", "pose_wave", {"hair": "hair_long"}),
        ("expr_happy", "pose_wave", {"hat": "hat_cap"}),
        ("expr_happy", "pose_wave", {"hat": "hat_crown"}),
        ("expr_happy", "pose_wave", {"outfit": "outfit_tie"}),
        ("expr_happy", "pose_wave", {"outfit": "outfit_scarf"}),
        ("expr_happy", "pose_wave", {"prop": "prop_book"}),
        ("expr_happy", "pose_wave", {"prop": "prop_mug"}),
    ],
)
def test_6_default_style_renders_each_character_asset(
    registry: Registry,
    style_id: str,
    expression: str,
    pose: str,
    slots: dict[str, str],
) -> None:
    frame, record, parts = _compose(
        registry,
        style_id,
        background="bg_park",
        theme="day",
        character=_character(**slots),
        expression=expression,
        pose=pose,
    )
    assert frame.size == (1080, 1920)
    assert {"body", "pose", "face", "expression", "hair", "skin"} <= set(parts)
    assert record["caption"]["lines"][0]["text"] == CAPTION


@pytest.mark.parametrize("style_id", STYLES)
def test_6_default_style_renders_every_theme_background(
    registry: Registry, style_id: str
) -> None:
    manifest = _manifest(registry, style_id)
    for theme in manifest.themes:
        for background in theme.backgrounds:
            frame, _, _ = _compose(
                registry,
                style_id,
                background=background,
                theme=theme.id,
                character=CANDIDATE,
            )
            assert frame.size == (1080, 1920)


@pytest.mark.parametrize("style_id", STYLES)
def test_6_default_style_renders_an_icon_asset(
    registry: Registry, style_id: str
) -> None:
    frame, _, _ = _compose(
        registry,
        style_id,
        background="bg_park",
        theme="day",
        character=CANDIDATE,
        with_icon=True,
    )
    assert frame.size == (1080, 1920)


@pytest.mark.parametrize("style_id", STYLES)
def test_6_default_style_draws_the_candidate_scene_sample(
    registry: Registry, style_id: str
) -> None:
    """The park, waving character and caption the drawn candidates show."""
    frame, _, _ = _compose(
        registry, style_id, background="bg_park", theme="day", character=CANDIDATE
    )
    manifest = _manifest(registry, style_id)
    day = next(theme for theme in manifest.themes if theme.id == "day")
    background = tuple(int(day.palette.bg[index:index + 2], 16) for index in (1, 3, 5))
    assert frame.getpixel((4, 4))[:3] == background
    directory = os.environ.get("STYLE_SAMPLE_DIR")
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        frame.convert("RGB").save(target / f"{style_id}.png")
