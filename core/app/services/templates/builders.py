"""Sandbox-backed parts builder and layer drawer for generated packages.

A generated style stores the asset PNGs its program drew when it was accepted,
so a saved style is reused without the model or the sandbox. A package without
stored assets for a request runs its program in the sandbox; the adapter caches
that result by code, runtime, input and seed. Generated templates always draw
through the sandbox because the layer depends on each scene.
"""

from __future__ import annotations

import base64
import hashlib
import io
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image

from app.ports import AppError, CancelToken, CatalogPort, SandboxPort, UnknownCatalogId
from app.schemas.common import PinnedRef
from app.schemas.sandbox_io import SandboxAsset, SandboxKind, SandboxLimits, SandboxRequest
from app.schemas.scene import Scene
from app.schemas.settings import CharacterSpec
from app.schemas.style_manifest import AssetKind, StyleManifest
from app.schemas.template_manifest import TemplateManifest
from app.services.templates import sprites


def encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


LAYER_ORDER = ("body", "pose", "outfit", "face", "expression", "hair", "hat", "prop")
MAX_FILES = 64
MAX_PNG_SIDE = 1920
MAX_WAV_MS = 16000


def sandbox_request(
    kind: SandboxKind,
    code: str,
    input: dict[str, Any],
    seed: int,
    assets: Mapping[str, bytes] | None = None,
) -> SandboxRequest:
    return SandboxRequest(
        protocol=1,
        request_id=secrets.token_hex(8),
        kind=kind,
        code=code,
        input=input,
        assets=[
            SandboxAsset(name=name, png_b64=base64.b64encode(data).decode("ascii"))
            for name, data in sorted((assets or {}).items())
        ],
        seed=seed,
        limits=SandboxLimits(max_files=MAX_FILES, max_png_side=MAX_PNG_SIDE, max_wav_ms=MAX_WAV_MS),
    )


def style_spec(manifest: StyleManifest) -> dict[str, Any]:
    """Every asset id the program draws, grouped by kind; slot ids stay the base ids."""
    backgrounds: list[str] = []
    skins: list[str] = []
    for theme in manifest.themes:
        backgrounds.extend(item for item in theme.backgrounds if item not in backgrounds)
        if theme.skin_id not in skins:
            skins.append(theme.skin_id)
    return {
        "parts": manifest.rig.slots.model_dump(mode="json"),
        "expressions": list(manifest.rig.expressions),
        "poses": list(manifest.rig.poses),
        "backgrounds": backgrounds,
        "skins": skins,
        "icons": [asset.id for asset in manifest.assets if asset.kind is AssetKind.icon],
    }


def spec_assets(spec: Mapping[str, Any]) -> dict[str, tuple[AssetKind, str | None]]:
    """Asset id to (kind, slot) for every id named by ``style_spec``."""
    assets: dict[str, tuple[AssetKind, str | None]] = {}
    for slot, ids in spec["parts"].items():
        for asset_id in ids:
            assets[asset_id] = (AssetKind.part, slot)
    for key, kind in (
        ("expressions", AssetKind.expression),
        ("poses", AssetKind.pose),
        ("backgrounds", AssetKind.background),
        ("skins", AssetKind.skin),
        ("icons", AssetKind.icon),
    ):
        for asset_id in spec[key]:
            assets.setdefault(asset_id, (kind, None))
    return assets


def character_input(character: CharacterSpec, expression_id: str, pose_id: str) -> dict[str, Any]:
    return {
        "slots": character.slots.model_dump(mode="json"),
        "expression": expression_id,
        "pose": pose_id,
    }


def chosen_layers(
    manifest: StyleManifest, character: CharacterSpec, expression_id: str, pose_id: str
) -> dict[str, str]:
    """Layer name to asset id for one character; rejects ids outside the rig."""
    rig = manifest.rig
    allowed = rig.slots.model_dump()
    chosen: dict[str, str] = {}
    for slot, asset_id in character.slots.model_dump().items():
        if asset_id is None:
            continue
        if asset_id not in allowed[slot]:
            raise AppError("unknown_catalog_id", detail={"kind": slot, "id": asset_id})
        chosen[slot] = asset_id
    if expression_id not in rig.expressions:
        raise AppError("unknown_catalog_id", detail={"kind": "expression", "id": expression_id})
    if pose_id not in rig.poses:
        raise AppError("unknown_catalog_id", detail={"kind": "pose", "id": pose_id})
    chosen["expression"] = expression_id
    chosen["pose"] = pose_id
    for rule in rig.compat:
        if rule.asset_id in chosen.values() and chosen["body"] not in rule.body_ids:
            raise AppError(
                "incompatible_part", detail={"asset": rule.asset_id, "body": chosen["body"]}
            )
    return {name: chosen[name] for name in LAYER_ORDER if name in chosen}


def read_program(root: Path, program: str, digest: str) -> str:
    data = (root / program).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise AppError("internal", detail={"reason": "program digest mismatch"})
    return data.decode("utf-8")


def stored_asset(root: Path, manifest: StyleManifest, asset_id: str) -> bytes | None:
    """The stored sprite grid of one asset, checked against the manifest digest."""
    asset = next((item for item in manifest.assets if item.id == asset_id), None)
    if asset is None or not asset.file.endswith(".json"):
        return None
    data = (root / asset.file).read_bytes()
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        raise AppError("internal", detail={"reason": "asset digest mismatch", "id": asset_id})
    return data


def _skin_invalid(reason: str) -> AppError:
    return AppError("render_input_invalid", detail={"input": "skin", "reason": reason})


class GeneratedPartsBuilder:
    """``PartsBuilder`` for styles whose renderer kind is ``sandbox``."""

    def __init__(self, catalog: CatalogPort, sandbox: SandboxPort) -> None:
        self.catalog = catalog
        self.sandbox = sandbox

    def _open(self, style: PinnedRef) -> tuple[StyleManifest, Path]:
        try:
            manifest = self.catalog.get("art_style", style.id, style.revision)
            root = self.catalog.package_dir("art_style", style)
        except UnknownCatalogId as error:
            raise AppError(
                "unknown_catalog_id", detail={"kind": "art_style", "id": style.id}
            ) from error
        if not isinstance(manifest, StyleManifest) or manifest.renderer.kind != "sandbox":
            raise AppError("unknown_catalog_id", detail={"kind": "art_style", "id": style.id})
        return manifest, root

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
        """Aligned part PNGs keyed by layer name; empty without a character.

        Stored assets ignore ``seed``: they are the drawing accepted at generation.
        """
        cancel.raise_if_set()
        manifest, root = self._open(style)
        if character is None:
            return {}
        spec = CharacterSpec.model_validate(character)
        layers = chosen_layers(manifest, spec, expression_id, pose_id)
        stored = {name: stored_asset(root, manifest, asset_id) for name, asset_id in layers.items()}
        if all(data is not None for data in stored.values()):
            return {
                name: encode_png(sprites.rasterize(data))
                for name, data in stored.items()
                if data is not None
            }
        renderer = manifest.renderer
        assert renderer.kind == "sandbox"
        code = read_program(root, renderer.program, renderer.program_digest)
        output = self.sandbox.run(
            sandbox_request(
                SandboxKind.style_parts,
                code,
                {
                    "spec": style_spec(manifest),
                    "character": character_input(spec, expression_id, pose_id),
                    "canvas": {"width": manifest.canvas.width, "height": manifest.canvas.height},
                },
                seed,
            ),
            cancel=cancel,
        )
        missing = [asset_id for asset_id in layers.values() if asset_id not in output.files]
        if missing:
            raise AppError(
                "sandbox_output_invalid", detail={"reason": f"program did not draw {missing[0]}"}
            )
        return {name: output.files[asset_id] for name, asset_id in layers.items()}

    def theme_parts(self, style: PinnedRef, theme_id: str) -> dict[str, bytes]:
        """The theme's box skin at one pixel per grid cell, as the ``skin`` part."""
        manifest, root = self._open(style)
        theme = next((item for item in manifest.themes if item.id == theme_id), None)
        if theme is None:
            raise AppError("unknown_catalog_id", detail={"kind": "theme", "id": theme_id})
        asset = next((item for item in manifest.assets if item.id == theme.skin_id), None)
        if asset is None or asset.kind is not AssetKind.skin:
            raise _skin_invalid("missing")
        data = stored_asset(root, manifest, asset.id)
        if data is None:
            raise _skin_invalid("not_a_stored_grid")
        try:
            grid = sprites.rasterize(data, cell=1)
        except AppError as error:
            raise _skin_invalid("unreadable") from error
        return {"skin": encode_png(grid)}


class GeneratedLayerDrawer:
    """``LayerDrawer`` for templates whose renderer kind is ``sandbox``."""

    def __init__(self, catalog: CatalogPort, sandbox: SandboxPort) -> None:
        self.catalog = catalog
        self.sandbox = sandbox

    def draw_layer(
        self,
        template: PinnedRef,
        scene: Scene,
        canvas: tuple[int, int],
        parts: dict[str, bytes],
        seed: int,
        *,
        cancel: CancelToken,
    ) -> tuple[bytes | None, dict[str, Any]]:
        cancel.raise_if_set()
        try:
            manifest = self.catalog.get("template", template.id, template.revision)
            root = self.catalog.package_dir("template", template)
        except UnknownCatalogId as error:
            raise AppError(
                "unknown_catalog_id", detail={"kind": "template", "id": template.id}
            ) from error
        if not isinstance(manifest, TemplateManifest) or manifest.renderer.kind != "sandbox":
            raise AppError("unknown_catalog_id", detail={"kind": "template", "id": template.id})
        renderer = manifest.renderer
        code = read_program(root, renderer.program, renderer.program_digest)
        output = self.sandbox.run(
            sandbox_request(
                SandboxKind.template_layer,
                code,
                {
                    "scene": scene.model_dump(mode="json"),
                    "regions": manifest.regions.model_dump(mode="json"),
                    "canvas": {"width": canvas[0], "height": canvas[1]},
                },
                seed,
                parts,
            ),
            cancel=cancel,
        )
        return output.files["layer"], dict(output.meta.get("program") or {})


__all__ = [
    "LAYER_ORDER",
    "GeneratedLayerDrawer",
    "GeneratedPartsBuilder",
    "character_input",
    "chosen_layers",
    "read_program",
    "sandbox_request",
    "spec_assets",
    "style_spec",
    "stored_asset",
]
