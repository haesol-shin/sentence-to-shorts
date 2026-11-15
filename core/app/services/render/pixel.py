"""Builtin ``pixel`` art style: part PNGs drawn from the package sprite grids.

The builder reads only data files of the pinned style package. Every part comes
back as a PNG of the same frame size so the renderer stacks them in
``PART_LAYERS`` order without extra placement data.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from app.ports import AppError, CancelToken, CatalogPort, UnknownCatalogId
from app.schemas.common import PinnedRef
from app.schemas.settings import CharacterSpec
from app.schemas.style_manifest import AssetKind, StyleManifest, Theme
from app.services.render.sprites import Sprite, erase_mask, load_sprite, rasterize

BUILTIN_STYLE_MODULE = "pixel"
PART_LAYERS = ("body", "pose", "outfit", "face", "expression", "hair", "hat", "prop")
MAX_PART_SIDE = 1920


def encode_png(image: Image.Image) -> bytes:
    """PNG bytes without metadata chunks, so equal pixels give equal bytes."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


def decode_png(data: bytes, name: str) -> Image.Image:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AppError("render_input_invalid", detail={"input": name, "reason": "not_png"})
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if max(opened.size) > MAX_PART_SIDE:
                raise AppError(
                    "render_input_invalid", detail={"input": name, "reason": "too_large"}
                )
            opened.load()
            return opened.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise AppError(
            "render_input_invalid", detail={"input": name, "reason": "undecodable"}
        ) from error


def _unknown(kind: str, item_id: str) -> AppError:
    return AppError("unknown_catalog_id", detail={"kind": kind, "id": item_id})


@dataclass(frozen=True)
class StylePackage:
    """A pinned style manifest and its package folder."""

    manifest: StyleManifest
    root: Path

    def sprite(self, asset_id: str, kinds: set[AssetKind]) -> Sprite:
        asset = next((item for item in self.manifest.assets if item.id == asset_id), None)
        if asset is None or asset.kind not in kinds:
            raise _unknown("asset", asset_id)
        return load_sprite(self.root / asset.file, asset_id)

    def theme(self, theme_id: str) -> Theme:
        theme = next((item for item in self.manifest.themes if item.id == theme_id), None)
        if theme is None:
            raise _unknown("theme", theme_id)
        return theme


def open_style(catalog: CatalogPort, ref: PinnedRef) -> StylePackage:
    try:
        manifest = catalog.get("art_style", ref.id, ref.revision)
        root = catalog.package_dir("art_style", ref)
    except UnknownCatalogId as error:
        raise _unknown("art_style", ref.id) from error
    if not isinstance(manifest, StyleManifest):
        raise _unknown("art_style", ref.id)
    return StylePackage(manifest=manifest, root=root)


def _check_slots(manifest: StyleManifest, character: CharacterSpec) -> dict[str, str]:
    chosen: dict[str, str] = {}
    allowed = manifest.rig.slots.model_dump()
    for slot, asset_id in character.slots.model_dump().items():
        if asset_id is None:
            continue
        if asset_id not in allowed[slot]:
            raise _unknown(slot, asset_id)
        chosen[slot] = asset_id
    body = chosen["body"]
    for rule in manifest.rig.compat:
        if rule.asset_id in chosen.values() and body not in rule.body_ids:
            raise AppError(
                "incompatible_part", detail={"asset": rule.asset_id, "body": body}
            )
    return chosen


class PixelPartsBuilder:
    """``PartsBuilder`` for builtin styles whose renderer module is ``pixel``."""

    def __init__(self, catalog: CatalogPort) -> None:
        self.catalog = catalog

    def build_parts(
        self,
        style: PinnedRef,
        character: Any | None,
        expression_id: str,
        pose_id: str,
        seed: int,
        *,
        cancel: CancelToken,
    ) -> dict[str, bytes]:
        """Aligned part PNGs keyed by ``PART_LAYERS`` names; empty without a character.

        The builtin style is fixed art, so ``seed`` does not change the result.
        """
        cancel.raise_if_set()
        package = open_style(self.catalog, style)
        if character is None:
            return {}
        spec = CharacterSpec.model_validate(character)
        rig = package.manifest.rig
        if expression_id not in rig.expressions:
            raise _unknown("expression", expression_id)
        if pose_id not in rig.poses:
            raise _unknown("pose", pose_id)
        chosen = _check_slots(package.manifest, spec)
        sprites = {
            slot: package.sprite(asset_id, {AssetKind.part}) for slot, asset_id in chosen.items()
        }
        sprites["pose"] = package.sprite(pose_id, {AssetKind.pose})
        sprites["expression"] = package.sprite(expression_id, {AssetKind.expression})
        body = sprites["body"]
        cell = body.scale
        frame = (body.width * cell, body.height * cell)
        parts: dict[str, bytes] = {}
        for name in PART_LAYERS:
            cancel.raise_if_set()
            sprite = sprites.get(name)
            if sprite is None:
                continue
            layer = Image.new("RGBA", frame, (0, 0, 0, 0))
            ox, oy = sprite.origin
            layer.alpha_composite(rasterize(sprite, cell), (ox * cell, oy * cell))
            if name == "body":
                cleared = Image.new("RGBA", frame, (0, 0, 0, 0))
                layer = Image.composite(
                    layer, cleared, erase_mask(sprites["pose"], frame, cell)
                )
            parts[name] = encode_png(layer)
        return parts

    def theme_parts(self, style: PinnedRef, theme_id: str) -> dict[str, bytes]:
        """The theme's box skin at one pixel per grid cell, as the ``skin`` part."""
        package = open_style(self.catalog, style)
        theme = package.theme(theme_id)
        skin = package.sprite(theme.skin_id, {AssetKind.skin})
        return {"skin": encode_png(rasterize(skin, 1))}


__all__ = [
    "BUILTIN_STYLE_MODULE",
    "PART_LAYERS",
    "PixelPartsBuilder",
    "StylePackage",
    "decode_png",
    "encode_png",
    "open_style",
]
