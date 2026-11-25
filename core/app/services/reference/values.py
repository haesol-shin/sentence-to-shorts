"""From the model's answer to ``set`` ops with origin ``reference``.

The answer is advice. An op is built only when the value is a registered catalog
item, fits the video's art style, differs from the current value and replaces no
value a higher origin owns. Locked items, the confirmed concept and combinations
the semantic checks would refuse (CONTRACTS 1.3) are left out instead of being
proposed. Values left out because the user owns them are reported by pointer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.caption_layout import FRAME_HEIGHT, FRAME_WIDTH, clamp_place
from app.ports import CatalogPort, UnknownCatalogId
from app.schemas.change import SetOp
from app.schemas.common import CaptionMode, CharacterRole, Origin
from app.schemas.settings import CaptionPlace, LockKey, LockState, higher_origin_pointers
from app.schemas.video import STAGE_ORDER, Video, VideoStage
from app.services.reference.vision import ReferenceValues

SETTINGS = "/settings"
MIN_SCENES = 3
MAX_SCENES = 20


@dataclass
class Built:
    ops: list[SetOp] = field(default_factory=list)
    kept_user_values: list[str] = field(default_factory=list)


def _locked(video: Video, key: LockKey | None) -> bool:
    return key is not None and video.settings.locks.get(key) is LockState.locked


def _concept_open(video: Video) -> bool:
    return STAGE_ORDER.index(video.stage) < STAGE_ORDER.index(VideoStage.concept_confirmed)


def _get(catalog: CatalogPort, kind: str, item_id: str, revision: str | None = None) -> Any:
    try:
        return catalog.get(kind, item_id, revision)
    except UnknownCatalogId:
        return None


def _layout_fits(template: Any, style: Any, mode: CaptionMode) -> bool:
    if template is None or style is None:
        return False
    return (
        template.id in style.capabilities.layouts
        and mode in template.caption_modes
        and mode in style.capabilities.caption_modes
        and (mode is not CaptionMode.typewriter or template.dialog_box)
    )


def _role_fits(video: Video, style: Any, role: CharacterRole) -> bool:
    if style is None or role not in style.capabilities.character_roles:
        return False
    placed = any(
        scene.visual is not None and scene.visual.characters for scene in video.scenes.values()
    )
    if role is CharacterRole.none:
        return video.settings.visual.character is None and not placed
    return video.settings.visual.character is not None


def build(video: Video, values: ReferenceValues, scene_count: int, catalog: CatalogPort) -> Built:
    """Ops for the values this reference may set, and the pointers the user kept."""
    built = Built()
    settings = video.settings
    style = _get(
        catalog, "art_style", settings.visual.art_style.id, settings.visual.art_style.revision
    )

    def allowed(pointer: str, key: LockKey | None) -> bool:
        if higher_origin_pointers(settings.origins, pointer[len(SETTINGS) :], Origin.reference):
            built.kept_user_values.append(pointer)
            return False
        if _locked(video, key):
            built.kept_user_values.append(pointer)
            return False
        return True

    def op(pointer: str, value: Any) -> SetOp:
        return SetOp(op="set", path=pointer, value=value, origin=Origin.reference)

    simple: list[tuple[str, Any, Any, LockKey | None]] = [
        (
            "/settings/format/register",
            values.register_value,
            settings.format.register_value,
            LockKey.register,
        ),
        ("/settings/format/humor", values.humor, settings.format.humor, LockKey.humor),
        (
            "/settings/format/progress_mode",
            values.progress_mode,
            settings.format.progress_mode,
            None,
        ),
        ("/settings/audio/bgm/mood", values.bgm_mood, settings.audio.bgm.mood, LockKey.bgm),
    ]
    for pointer, proposed, current, key in simple:
        if proposed is not None and proposed != current and allowed(pointer, key):
            built.ops.append(op(pointer, proposed.value))

    structure = values.story_structure
    pointer = "/settings/format/story_structure"
    if (
        structure is not None
        and structure != settings.format.story_structure
        and _concept_open(video)
        and _get(catalog, "story_structure", structure) is not None
        and allowed(pointer, LockKey.story_structure)
    ):
        built.ops.append(op(pointer, structure))

    role = values.character_role
    pointer = "/settings/format/character_role"
    if (
        role is not None
        and role != settings.format.character_role
        and _role_fits(video, style, role)
        and allowed(pointer, LockKey.character_role)
    ):
        built.ops.append(op(pointer, role.value))

    if not video.scene_order and scene_count != settings.format.scene_count:
        pointer = "/settings/format/scene_count"
        if allowed(pointer, None):
            built.ops.append(op(pointer, min(MAX_SCENES, max(MIN_SCENES, scene_count))))

    _layout_and_captions(video, values, catalog, style, built, allowed, op)
    _caption_place(video, values, built, allowed, op)
    return built


def _caption_place(
    video: Video, values: ReferenceValues, built: Built, allowed: Any, op: Any
) -> None:
    """The reference caption plate as one place op, when it reads cleanly.

    Ratios outside 0 to 1, a plate with no width or height and a plate the store
    would refuse are dropped: a weak reading must not fail the whole analysis.
    """
    ratios = values.caption_place
    if ratios is None:
        return
    numbers = (ratios.y_top, ratios.y_bottom, ratios.x_left, ratios.x_right)
    if any(not 0.0 <= value <= 1.0 for value in numbers):
        return
    if ratios.x_right <= ratios.x_left or ratios.y_bottom <= ratios.y_top:
        return
    raw: dict[str, Any] = {
        "y": round(ratios.y_top * FRAME_HEIGHT) - 4,
        "x": round(ratios.x_left * FRAME_WIDTH),
        "w": round((ratios.x_right - ratios.x_left) * FRAME_WIDTH),
        "align": ratios.align or "center",
    }
    clamped, _ = clamp_place(raw)
    try:
        place = CaptionPlace.model_validate(clamped)
    except ValidationError:
        return
    if place == video.settings.caption.place:
        return
    pointer = "/settings/caption/place"
    if not allowed(pointer, None):
        return
    built.ops.append(op(pointer, place.model_dump(mode="json")))


def _layout_and_captions(
    video: Video, values: ReferenceValues, catalog: CatalogPort, style: Any, built: Built,
    allowed: Any, op: Any,
) -> None:
    """Layout and caption mode are proposed together only when they fit together."""
    settings = video.settings
    layout_pointer = "/settings/format/layout"
    mode_pointer = "/settings/caption/mode"
    new_template = None
    if values.layout is not None and values.layout != settings.format.layout.id:
        new_template = _get(catalog, "template", values.layout)
    if new_template is not None and not allowed(layout_pointer, LockKey.layout):
        new_template = None
    mode = values.caption_mode if values.caption_mode != settings.caption.mode else None
    if mode is not None and not allowed(mode_pointer, LockKey.caption_mode):
        mode = None
    current = _get(
        catalog, "template", settings.format.layout.id, settings.format.layout.revision
    )
    options: list[tuple[Any, CaptionMode | None]] = [
        (new_template, mode),
        (new_template, None),
        (None, mode),
    ]
    for template, proposed in options:
        if template is None and proposed is None:
            continue
        if not _layout_fits(template or current, style, proposed or settings.caption.mode):
            continue
        if template is not None:
            pinned = catalog.pin("template", template.id).model_dump(mode="json")
            built.ops.append(op(layout_pointer, pinned))
        if proposed is not None:
            built.ops.append(op(mode_pointer, proposed.value))
        return
