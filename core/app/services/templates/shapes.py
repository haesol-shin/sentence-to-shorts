"""Shape difference check: compare colour-free masks of the same test character.

A layer with transparent pixels becomes its alpha mask. A fully opaque layer,
such as a background, becomes the mask of every pixel that differs from its most
common colour, so a palette swap keeps the same mask. A builtin pixel background
is a grid of palette keys; its mask is read the same way from the keys, so no
colour is involved. Masks of different sizes are compared at the base size with
nearest-neighbour scaling.

New style: every group present in either style (head, body, prop, background)
must reach an intersection over union below the threshold. Modification: the
face group (outline, plus the inner detail such as eyes) must change at least
one mask pixel in canvas coordinates, independent of the body's bounds.
"""

from __future__ import annotations

import io
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageChops

from app.ports import AppError

IOU_THRESHOLD_X1000 = 800
GROUPS: dict[str, tuple[str, ...]] = {
    "head": ("face", "expression", "hair", "hat"),
    "body": ("body", "pose", "outfit"),
    "prop": ("prop",),
    "background": ("background",),
}
FACE_GROUP = ("face", "expression")
MAX_SIDE = 1920


def decode(data: bytes, name: str) -> Image.Image:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if max(opened.size) > MAX_SIDE:
                raise AppError("sandbox_output_invalid", detail={"reason": f"{name} too large"})
            opened.load()
            return opened.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise AppError(
            "sandbox_output_invalid", detail={"reason": f"{name} is not a PNG"}
        ) from error


def shape_mask(image: Image.Image) -> Image.Image:
    """A colour-free ``L`` mask: 255 where the layer has shape, 0 elsewhere."""
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] < 255:
        return alpha.point(lambda value: 255 if value else 0)
    rgb = image.convert("RGB")
    colors = rgb.getcolors(maxcolors=rgb.width * rgb.height) or []
    common = max(colors, key=lambda item: item[0])[1]
    flat = Image.new("RGB", rgb.size, common)
    red, green, blue = ImageChops.difference(rgb, flat).split()
    changed = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return changed.point(lambda value: 255 if value else 0)


def _count(mask: Image.Image) -> int:
    return mask.histogram()[255]


def _union(layers: list[Image.Image]) -> Image.Image | None:
    if not layers:
        return None
    merged = shape_mask(layers[0])
    for layer in layers[1:]:
        mask = shape_mask(layer)
        if mask.size != merged.size:
            mask = mask.resize(merged.size, Image.Resampling.NEAREST)
        merged = ImageChops.lighter(merged, mask)
    return merged


def group_mask(parts: Mapping[str, bytes], names: tuple[str, ...]) -> Image.Image | None:
    return _union([decode(parts[name], name) for name in names if name in parts])


def group_masks(parts: Mapping[str, bytes]) -> dict[str, Image.Image | None]:
    """Character groups cropped to their bounds; face masks in canvas coordinates.

    Styles place the character on frames of different sizes, so the crop makes
    the comparison about the drawn shapes, not where the frame put them.
    Face masks keep the full canvas so body changes cannot alter their alignment.
    """
    character = tuple(
        layer for name, layers in GROUPS.items() if name != "background" for layer in layers
    )
    whole = group_mask(parts, character)
    box = whole.getbbox() if whole is not None else None
    masks: dict[str, Image.Image | None] = {}
    for name, layers in GROUPS.items():
        if name == "background":
            continue
        masks[name] = _fit(group_mask(parts, layers), whole, box)
    masks["face"] = group_mask(parts, FACE_GROUP)
    masks["face_detail"] = _detail(parts, FACE_GROUP)
    return masks


def _fit(
    mask: Image.Image | None, whole: Image.Image | None, box: tuple[int, int, int, int] | None
) -> Image.Image | None:
    if mask is None or whole is None or box is None:
        return mask
    if mask.size != whole.size:
        mask = mask.resize(whole.size, Image.Resampling.NEAREST)
    return mask.crop(box)


def _detail(parts: Mapping[str, bytes], names: tuple[str, ...]) -> Image.Image | None:
    """Inner structure of stacked layers, such as eyes drawn inside a face.

    The layers are stacked in order and every opaque pixel whose colour differs
    from the most common opaque colour is marked. A palette swap keeps the mask;
    moving or reshaping an inner feature changes it.
    """
    layers = [decode(parts[name], name) for name in names if name in parts]
    if not layers:
        return None
    stacked = Image.new("RGBA", layers[0].size, (0, 0, 0, 0))
    for layer in layers:
        if layer.size != stacked.size:
            layer = layer.resize(stacked.size, Image.Resampling.NEAREST)
        stacked.alpha_composite(layer)
    opaque = stacked.getchannel("A").point(lambda value: 255 if value else 0)
    rgb = stacked.convert("RGB")
    counts: Counter[tuple[int, int, int]] = Counter()
    for count, (red, green, blue, alpha) in stacked.getcolors(stacked.width * stacked.height):
        if alpha:
            counts[(red, green, blue)] += count
    if not counts:
        return opaque
    common = counts.most_common(1)[0][0]
    flat = Image.new("RGB", rgb.size, common)
    red, green, blue = ImageChops.difference(rgb, flat).split()
    differs = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return ImageChops.darker(differs.point(lambda value: 255 if value else 0), opaque)


def grid_mask(raw: object) -> Image.Image | None:
    """Mask of a pixel sprite grid at its own scale; None when the data is not a grid."""
    if not isinstance(raw, dict):
        return None
    rows, scale = raw.get("rows"), raw.get("scale")
    if (
        not isinstance(rows, list)
        or not rows
        or not all(isinstance(row, str) and len(row) == len(rows[0]) for row in rows)
        or not isinstance(scale, int)
        or not 1 <= scale <= 32
        or len(rows[0]) * scale > MAX_SIDE
        or len(rows) * scale > MAX_SIDE
    ):
        return None
    keys = [key for row in rows for key in row]
    if not keys:
        return None
    common = max(set(keys), key=keys.count)
    mask = Image.new("L", (len(rows[0]), len(rows)), 0)
    mask.putdata([255 if key not in (common, ".") else 0 for key in keys])
    return mask.resize((mask.width * scale, mask.height * scale), Image.Resampling.NEAREST)


def _aligned(
    base: Image.Image | None, other: Image.Image | None
) -> tuple[Image.Image, Image.Image]:
    size = (base or other).size  # type: ignore[union-attr]
    empty = Image.new("L", size, 0)
    first = base if base is not None else empty
    second = other if other is not None else empty
    if second.size != size:
        second = second.resize(size, Image.Resampling.NEAREST)
    return first, second


def iou_x1000(base: Image.Image | None, other: Image.Image | None) -> int | None:
    """Intersection over union in thousandths; None when both masks are empty."""
    if base is None and other is None:
        return None
    first, second = _aligned(base, other)
    union = _count(ImageChops.lighter(first, second))
    if union == 0:
        return None
    return _count(ImageChops.darker(first, second)) * 1000 // union


def changed_pixels(base: Image.Image | None, other: Image.Image | None) -> int:
    if base is None and other is None:
        return 0
    first, second = _aligned(base, other)
    return _count(ImageChops.difference(first, second))


@dataclass(frozen=True)
class ShapeReport:
    """Measured values and the rule; written into the package and the job error."""

    mode: str
    passed: bool
    groups: dict[str, dict[str, Any]]
    face_changed_pixels: int | None

    def as_json(self) -> dict[str, Any]:
        rule = (
            "every compared group iou below threshold"
            if self.mode == "new"
            else "face outline or inner detail mask changes at least one pixel"
        )
        return {
            "mode": self.mode,
            "rule": rule,
            "threshold_iou_x1000": IOU_THRESHOLD_X1000,
            "passed": self.passed,
            "groups": self.groups,
            "face_changed_pixels": self.face_changed_pixels,
        }

    def error_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "reason": "color_only" if self.mode == "new" else "face_unchanged",
            "threshold_iou_x1000": IOU_THRESHOLD_X1000,
        }
        for name, group in self.groups.items():
            if group.get("iou_x1000") is not None:
                detail[f"{name}_iou_x1000"] = group["iou_x1000"]
        if self.face_changed_pixels is not None:
            detail["face_changed_pixels"] = self.face_changed_pixels
        return detail


def compare(
    base: Mapping[str, Image.Image | None],
    candidate: Mapping[str, Image.Image | None],
    *,
    modification: bool,
    skipped: Mapping[str, str] | None = None,
) -> ShapeReport:
    """Compare group masks of the base and candidate test character.

    ``skipped`` names groups the base cannot provide and why; they are reported
    as not compared instead of counting as a shape change.
    """
    groups: dict[str, dict[str, Any]] = {}
    compared: list[int] = []
    for name in GROUPS:
        if skipped and name in skipped:
            groups[name] = {"compared": False, "reason": skipped[name]}
            continue
        value = iou_x1000(base.get(name), candidate.get(name))
        if value is None:
            groups[name] = {"compared": False, "reason": "empty in both"}
            continue
        groups[name] = {"compared": True, "iou_x1000": value}
        compared.append(value)
    if modification:
        face = changed_pixels(base.get("face"), candidate.get("face")) + changed_pixels(
            base.get("face_detail"), candidate.get("face_detail")
        )
        return ShapeReport("modify", face > 0, groups, face)
    passed = bool(compared) and all(value < IOU_THRESHOLD_X1000 for value in compared)
    return ShapeReport("new", passed, groups, None)


__all__ = [
    "IOU_THRESHOLD_X1000",
    "ShapeReport",
    "compare",
    "decode",
    "grid_mask",
    "group_masks",
    "shape_mask",
]
