"""Builtin pixel style: registry validation, themes, fonts and part PNGs."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.plugins.registry import Registry
from app.ports import AppError
from app.schemas.font_manifest import FontManifest
from app.schemas.settings import CharacterSpec
from app.schemas.style_manifest import AssetKind, StyleManifest
from app.services.render import PART_LAYERS, PixelPartsBuilder

# Ids that existed before the themes were filled; they must stay registered.
ORIGINAL_IDS = {
    "body_hero",
    "face_neutral",
    "expr_happy",
    "expr_surprised",
    "pose_idle",
    "pose_wave",
    "bg_village",
    "bg_stars",
    "skin_plain",
    "icon_arrow",
}
FULL_CHARACTER = CharacterSpec.model_validate(
    {
        "preset_id": None,
        "slots": {
            "body": "body_round",
            "face": "face_glasses",
            "hair": "hair_short",
            "hat": "hat_cap",
            "outfit": "outfit_tie",
            "prop": "prop_mug",
        },
    }
)


class Token:
    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


@pytest.fixture(scope="module")
def registry() -> Registry:
    registry = Registry()
    registry.load()
    return registry


@pytest.fixture(scope="module")
def pixel(registry: Registry) -> StyleManifest:
    manifest = registry.get("art_style", "pixel")
    assert isinstance(manifest, StyleManifest)
    return manifest


def _png(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_6_pixel_style_has_three_filled_themes(pixel: StyleManifest) -> None:
    assets = {asset.id: asset for asset in pixel.assets}
    assert ORIGINAL_IDS <= set(assets)
    assert len(pixel.themes) == 3
    for theme in pixel.themes:
        assert 3 <= len(theme.backgrounds) <= 4
        assert all(assets[item].kind == AssetKind.background for item in theme.backgrounds)
        assert assets[theme.skin_id].kind == AssetKind.skin
    assert len({theme.skin_id for theme in pixel.themes}) == 3
    assert len({theme.palette.bg for theme in pixel.themes}) == 3
    for slot, items in pixel.rig.slots.model_dump().items():
        assert 2 <= len(items) <= 3, slot
        assert all(assets[item].slot == slot for item in items)


def test_6_catalog_lists_the_pixel_themes(client: TestClient) -> None:
    listing = client.get("/api/v1/catalog/art_style")
    assert listing.status_code == 200
    assert "pixel" in [item["id"] for item in listing.json()["items"]]
    manifest = client.get("/api/v1/catalog/art_style/pixel").json()
    assert [theme["id"] for theme in manifest["themes"]] == ["day", "moonlight", "arcade"]


def test_24_pixel_style_offers_bundled_licensed_fonts(
    registry: Registry, pixel: StyleManifest
) -> None:
    assert 2 <= len(pixel.fonts) <= 3
    for font_id in pixel.fonts:
        manifest = registry.get("font", font_id)
        assert isinstance(manifest, FontManifest)
        assert manifest.license.spdx == "OFL-1.1"
        root = registry.package_dir("font", registry.pin("font", font_id))
        assert (root / manifest.file).is_file()
        assert "SIL OPEN FONT LICENSE" in (root / manifest.license.license_file).read_text(
            encoding="utf-8"
        ).upper()
        assert {"hangul", "latin", "digits"} <= {script.value for script in manifest.scripts}


def test_6_parts_builder_returns_aligned_part_pngs(registry: Registry) -> None:
    builder = PixelPartsBuilder(registry)
    style = registry.pin("art_style", "pixel")
    parts = builder.build_parts(style, FULL_CHARACTER, "expr_happy", "pose_wave", 7, cancel=Token())
    assert list(parts) == list(PART_LAYERS)
    sizes = {_png(data).size for data in parts.values()}
    assert sizes == {(100, 160)}
    assert builder.build_parts(style, None, "expr_happy", "pose_idle", 0, cancel=Token()) == {}


def test_6_wave_pose_clears_the_lowered_arm(registry: Registry) -> None:
    builder = PixelPartsBuilder(registry)
    style = registry.pin("art_style", "pixel")
    idle = builder.build_parts(style, FULL_CHARACTER, "expr_happy", "pose_idle", 0, cancel=Token())
    wave = builder.build_parts(style, FULL_CHARACTER, "expr_happy", "pose_wave", 0, cancel=Token())
    arm = (95, 95)  # grid cell (9, 9) at ten pixels per cell
    assert _png(idle["body"]).convert("RGBA").getpixel(arm)[3] == 255
    assert _png(wave["body"]).convert("RGBA").getpixel(arm)[3] == 0
    assert _png(wave["pose"]).convert("RGBA").getpixel((95, 45))[3] == 255


@pytest.mark.parametrize(
    ("expression", "pose", "slots"),
    [
        ("expr_missing", "pose_idle", {}),
        ("expr_happy", "pose_missing", {}),
        ("expr_happy", "pose_idle", {"hat": "bg_village"}),
    ],
)
def test_6_parts_builder_rejects_ids_outside_the_rig(
    registry: Registry, expression: str, pose: str, slots: dict[str, str]
) -> None:
    character = FULL_CHARACTER.model_copy(
        update={"slots": FULL_CHARACTER.slots.model_copy(update=slots)}
    )
    builder = PixelPartsBuilder(registry)
    with pytest.raises(AppError) as error:
        builder.build_parts(
            registry.pin("art_style", "pixel"), character, expression, pose, 0, cancel=Token()
        )
    assert error.value.code == "unknown_catalog_id"


def test_6_every_theme_skin_renders(registry: Registry, pixel: StyleManifest) -> None:
    builder = PixelPartsBuilder(registry)
    style = registry.pin("art_style", "pixel")
    skins = {
        theme.id: builder.theme_parts(style, theme.id)["skin"] for theme in pixel.themes
    }
    assert len(set(skins.values())) == 3
    assert all(_png(data).size[0] >= 7 for data in skins.values())

