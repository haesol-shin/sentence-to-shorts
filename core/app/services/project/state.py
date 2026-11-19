"""Typed project and video state: defaults, op application and semantic checks.

Every function here is pure apart from catalog lookups. Nothing writes a store,
so the service decides when a result becomes a revision.

Value precedence follows CONTRACTS 1.2: user > reference > preset > card > llm >
default. A lower origin never replaces a higher one, a locked item never changes
and the concept values never change after the concept is confirmed, unless the
caller passes the matching confirmation. Values left in place are reported, so
a change plan can ask for that confirmation.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.caption_layout import (
    caption_inner,
    place_pair,
    smallest_caption_height,
)
from app.ports import AppError, CatalogPort, Issue, UnknownCatalogId
from app.schemas.bgm_entry import SfxEntry, SfxKind, TypingSoundEntry
from app.schemas.caption_language_manifest import CaptionLanguageManifest
from app.schemas.change import (
    AddSceneOp,
    ChangePlan,
    ChangeSource,
    ConfirmationReason,
    Op,
    RemoveSceneOp,
    ReorderOp,
    ReplaceSceneOp,
    SetOp,
    SetScriptOp,
)
from app.schemas.common import (
    CaptionMode,
    CharacterRole,
    Language,
    Mood,
    Origin,
    PinnedRef,
)
from app.schemas.font_manifest import FontManifest, FontScript
from app.schemas.scene import ElementKind, Scene
from app.schemas.settings import (
    ORIGIN_POINTER_PATTERN,
    ORIGIN_RANK,
    Audio,
    BgmSettings,
    Caption,
    CaptionLayer,
    CaptionPosition,
    CharacterMotion,
    CharacterSlots,
    CharacterSpec,
    Format,
    Humor,
    LockKey,
    LockState,
    Motion,
    ProgressMode,
    Register,
    Settings,
    Transition,
    Visual,
    higher_origin_pointers,
)
from app.schemas.video import STAGE_ORDER, Video, VideoStage, stage_after_script_rewrite

SOURCE_ORIGIN: dict[ChangeSource, Origin] = {
    ChangeSource.direct: Origin.user,
    ChangeSource.chat: Origin.user,
    ChangeSource.scene_rewrite: Origin.user,
    ChangeSource.style: Origin.user,
    ChangeSource.template: Origin.user,
    ChangeSource.bgm: Origin.user,
    ChangeSource.card: Origin.card,
    ChangeSource.reference: Origin.reference,
}
"""Highest origin a plan of each source may record. Chat counts as user input."""

SETTINGS = "/settings"

LOCK_POINTERS: dict[LockKey, str] = {
    LockKey.story_structure: "/settings/format/story_structure",
    LockKey.layout: "/settings/format/layout",
    LockKey.character_role: "/settings/format/character_role",
    LockKey.register: "/settings/format/register",
    LockKey.humor: "/settings/format/humor",
    LockKey.art_style: "/settings/visual/art_style",
    LockKey.theme: "/settings/visual/theme_id",
    LockKey.character: "/settings/visual/character",
    LockKey.voice: "/settings/audio/voice",
    LockKey.bgm: "/settings/audio/bgm",
    LockKey.caption_mode: "/settings/caption/mode",
    LockKey.caption_font: "/settings/caption/font_id",
    LockKey.transition: "/settings/motion/transition",
}
"""Settings pointer of each lock key. LockKey.background guards scene backgrounds."""

CONCEPT_POINTERS = (
    "/settings/format/story_structure",
    "/settings/visual/art_style",
    "/settings/visual/character",
)

DEFAULT_LOCKS: dict[LockKey, LockState] = {
    LockKey.art_style: LockState.locked,
    LockKey.character: LockState.locked,
    LockKey.voice: LockState.locked,
    LockKey.theme: LockState.varied,
    LockKey.background: LockState.varied,
    LockKey.bgm: LockState.varied,
}

PREFERRED = {
    "story_structure": "numbered_three",
    "template": "fixed_stage",
    "art_style": "pixel",
    "voice": "fixed_wav",
}
"""First choice of each default. Any registered item is used when it is missing."""


def language_script(catalog: CatalogPort, language: Language) -> FontScript:
    """The font script the caption language catalog row for ``language`` needs."""
    try:
        entry = catalog.get("caption_language", language.value)
    except UnknownCatalogId as error:
        raise AppError(
            "unknown_catalog_id",
            detail={"kind": "caption_language", "id": language.value},
        ) from error
    if not isinstance(entry, CaptionLanguageManifest):
        raise AppError(
            "unknown_catalog_id",
            detail={"kind": "caption_language", "id": language.value},
        )
    return entry.script


_ORIGIN_KEY = re.compile(ORIGIN_POINTER_PATTERN)
_MISSING = object()


# Defaults


def _choose(catalog: CatalogPort, kind: str, accept: Any = None) -> str:
    """The preferred id when it is registered and accepted, else the first such id."""
    preferred = PREFERRED.get(kind)
    ids = [item.id for item in catalog.list(kind)]
    if preferred in ids:
        ids.remove(preferred)
        ids.insert(0, preferred)
    for item_id in ids:
        if accept is None or accept(catalog.get(kind, item_id)):
            return item_id
    raise AppError("unknown_catalog_id", detail={"kind": kind})


def default_settings(language: Language, catalog: CatalogPort) -> Settings:
    """Settings that make a video without any format card.

    Every value has origin default except the language, which the user picked.
    """
    style_ref = catalog.pin("art_style", _choose(catalog, "art_style"))
    style: Any = catalog.get("art_style", style_ref.id, style_ref.revision)
    script = language_script(catalog, language)
    font_id = next(
        (
            font
            for font in style.fonts
            if script in [value.value for value in catalog.get("font", font).scripts]
        ),
        None,
    )
    if font_id is None:
        raise AppError("unknown_catalog_id", detail={"kind": "font"})
    voice_id = _choose(
        catalog, "voice", lambda voice: language in [lang.value for lang in voice.languages]
    )
    role = (
        CharacterRole.presenter
        if CharacterRole.presenter in style.capabilities.character_roles
        else CharacterRole.none
    )
    character = None
    if role is not CharacterRole.none:
        slots = style.rig.slots
        character = CharacterSpec(
            preset_id=None,
            slots=CharacterSlots(
                body=slots.body[0], face=slots.face[0], hair=None, hat=None, outfit=None, prop=None
            ),
        )
    return Settings(
        language=language,
        target_duration_s=60,
        format=Format(
            card_id=None,
            story_structure=_choose(catalog, "story_structure"),
            layout=catalog.pin("template", _choose(catalog, "template")),
            character_role=role,
            register=Register.friendly,
            humor=Humor.none,
            progress_mode=ProgressMode.numbered,
            scene_count=8,
        ),
        visual=Visual(art_style=style_ref, theme_id=style.themes[0].id, character=character),
        audio=Audio(
            voice=catalog.pin("voice", voice_id),
            bgm=BgmSettings(
                enabled=True, mood=Mood.curious, entry=None, gain_db_x10=-120, ducking=True
            ),
            sfx_enabled=True,
        ),
        caption=Caption(
            mode=CaptionMode.sentence,
            font_id=catalog.pin("font", font_id),
            position=CaptionPosition.bottom,
            highlight=True,
        ),
        motion=Motion(transition=Transition.cut, character_motion=CharacterMotion.none),
        locks=dict(DEFAULT_LOCKS),
        origins={
            "/language": Origin.user,
            "/target_duration_s": Origin.default,
            "/format": Origin.default,
            "/visual": Origin.default,
            "/audio": Origin.default,
            "/caption": Origin.default,
            "/motion": Origin.default,
        },
        extra_instructions=[],
    )


# JSON pointer helpers


def _parts(pointer: str) -> list[str]:
    return pointer.split("/")[1:]


def _get(doc: Any, pointer: str) -> Any:
    node = doc
    for part in _parts(pointer):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return _MISSING
    return node


def _put(doc: Any, pointer: str, value: Any) -> None:
    """Replace the value at an existing pointer. Raises invalid_op when it is absent."""
    *parents, last = _parts(pointer)
    node = _get(doc, "/" + "/".join(parents)) if parents else doc
    if isinstance(node, dict) and last in node:
        node[last] = value
    elif isinstance(node, list) and last.isdigit() and int(last) < len(node):
        node[int(last)] = value
    else:
        raise AppError("invalid_op", detail={"pointer": pointer})


def _covers(ancestor: str, pointer: str) -> bool:
    return pointer == ancestor or pointer.startswith(ancestor + "/")


# Applying ops


@dataclass(frozen=True)
class Confirmed:
    """Confirmations the user gave for one plan."""

    overwrites: frozenset[str] = frozenset()
    locks: frozenset[LockKey] = frozenset()

    def allows_overwrite(self, pointer: str) -> bool:
        return any(_covers(allowed, pointer) for allowed in self.overwrites)


def confirmed_by(plan: ChangePlan) -> Confirmed:
    """What applying this plan confirms: only the reasons the plan asked for."""
    reasons = set(plan.confirmation_reasons)
    return Confirmed(
        overwrites=frozenset(plan.effects.overwrites_user_values)
        if ConfirmationReason.user_value_overwrite in reasons
        else frozenset(),
        locks=frozenset(plan.effects.locked_keys)
        if ConfirmationReason.lock_change in reasons
        else frozenset(),
    )


@dataclass
class Applied:
    """Result of applying ops. The lists name values that were left unchanged."""

    video: Video
    overwrites_user_values: list[str] = field(default_factory=list)
    locked_keys: list[LockKey] = field(default_factory=list)
    concept_changes: list[str] = field(default_factory=list)


def effective_origin(origin: Origin, ceiling: Origin) -> Origin:
    """An op never records an origin above the origin its caller may write."""
    return origin if ORIGIN_RANK[origin] <= ORIGIN_RANK[ceiling] else ceiling


def _origin_rank(origins: dict[str, str], rel: str) -> int:
    """Highest origin recorded at a settings pointer or any pointer containing it."""
    ranks = [ORIGIN_RANK[Origin(value)] for key, value in origins.items() if _covers(key, rel)]
    return max(ranks, default=0)


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True)


def _scene_index(doc: dict[str, Any], scene_id: str) -> int:
    if scene_id not in doc["scenes"]:
        raise AppError("invalid_op", detail={"scene_id": scene_id})
    return doc["scene_order"].index(scene_id) if scene_id in doc["scene_order"] else -1


def _apply_structure(doc: dict[str, Any], op: Op) -> None:
    """Scene and script ops. They carry no origin."""
    if isinstance(op, ReorderOp):
        if sorted(op.order) != sorted(doc["scene_order"]):
            raise AppError("invalid_op", detail={"op": "reorder"})
        doc["scene_order"] = list(op.order)
    elif isinstance(op, AddSceneOp):
        if op.scene.id in doc["scenes"]:
            raise AppError("invalid_op", detail={"scene_id": op.scene.id})
        position = 0 if op.after is None else _scene_index(doc, op.after) + 1
        doc["scenes"][op.scene.id] = _dump(op.scene)
        doc["scene_order"].insert(position, op.scene.id)
    elif isinstance(op, RemoveSceneOp):
        _scene_index(doc, op.scene_id)
        del doc["scenes"][op.scene_id]
        doc["scene_order"] = [item for item in doc["scene_order"] if item != op.scene_id]
    elif isinstance(op, ReplaceSceneOp):
        _scene_index(doc, op.scene.id)
        doc["scenes"][op.scene.id] = _dump(op.scene)
    elif isinstance(op, SetScriptOp):
        doc["script"] = _dump(op.script)
        doc["scenes"] = {scene.id: _dump(scene) for scene in op.scenes}
        doc["scene_order"] = [scene.id for scene in op.scenes]
        doc["stage"] = stage_after_script_rewrite(VideoStage(doc["stage"])).value



def _has(node: Any, part: str) -> bool:
    if isinstance(node, dict):
        return part in node
    return isinstance(node, list) and part.isdigit() and int(part) < len(node)


def _restore(before: dict[str, Any], after: dict[str, Any], pointer: str) -> str:
    """Put the earlier value at ``pointer`` back into ``after``.

    When an op removed the parent (for example set the character to null), the
    nearest ancestor that still has a place in ``after`` is restored as a whole,
    so a kept value never disappears with its parent. Returns the restored pointer.
    """
    target = pointer
    while target:
        parent, _, last = target.rpartition("/")
        old = _get(before, target)
        node = _get(after, parent) if parent else after
        if old is not _MISSING and _has(node, last):
            _put(after, target, copy.deepcopy(old))
            return target
        target = parent
    raise AppError("invalid_op", detail={"pointer": pointer})


def _restore_origins(before: dict[str, Any], after: dict[str, Any], pointer: str) -> None:
    """Origins below a restored settings pointer return to their earlier entries."""
    if not pointer.startswith(SETTINGS + "/"):
        return
    rel = pointer[len(SETTINGS) :]
    origins: dict[str, str] = after["settings"]["origins"]
    for key in [key for key in origins if _covers(rel, key)]:
        del origins[key]
    for key, value in before["settings"]["origins"].items():
        if _covers(rel, key):
            origins[key] = value


def _check_set_path(op: SetOp, origin: Origin) -> None:
    if op.path == f"{SETTINGS}/origins" or op.path.startswith(f"{SETTINGS}/origins/"):
        raise AppError("invalid_op", detail={"pointer": op.path})
    if _covers(f"{SETTINGS}/locks", op.path) and origin is not Origin.user:
        raise AppError("invalid_op", detail={"pointer": op.path})


def _lock_pointers(before: dict[str, Any], after: dict[str, Any]) -> Iterator[tuple[LockKey, str]]:
    """Pointers each lock key protects. A scene background stays protected while
    the scene exists, so clearing its visual is a change of the locked value too.
    Removing the whole scene is not."""
    for key, pointer in LOCK_POINTERS.items():
        yield key, pointer
    for scene_id, scene in before["scenes"].items():
        if scene.get("visual") and scene_id in after["scenes"]:
            yield LockKey.background, f"/scenes/{scene_id}/visual/background_id"


class _Guard:
    """Keeps values a plan may not change, comparing two states of the document."""

    def __init__(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
        confirmed: Confirmed,
        result: Applied,
    ) -> None:
        self.before = before
        self.after = after
        self.confirmed = confirmed
        self.result = result
        self.kept: list[str] = []

    def changed(self, pointer: str) -> bool:
        return _get(self.before, pointer) != _get(self.after, pointer)

    def restore(self, pointer: str) -> None:
        target = _restore(self.before, self.after, pointer)
        _restore_origins(self.before, self.after, target)
        self.kept.append(target)

    def origins(self, path: str, origin: Origin) -> None:
        """One op against the state before it: a lower origin keeps higher values."""
        rel = path[len(SETTINGS) :]
        origins: dict[str, str] = self.before["settings"]["origins"]
        higher = higher_origin_pointers(origins, rel, origin)
        for key in higher:
            pointer = SETTINGS + key
            if self.changed(pointer) and not self.confirmed.allows_overwrite(pointer):
                self.restore(pointer)
                _append_once(self.result.overwrites_user_values, pointer)

    def locks(self) -> None:
        """The whole plan against its start: locked items and the locks themselves.

        Comparing with the start means an unlock earlier in the same plan, or an
        emptied and refilled scene visual, cannot hide a change of a locked item.
        """
        locked = LockState.locked.value
        start: dict[str, str] = self.before["settings"]["locks"]
        final: dict[str, str] = self.after["settings"]["locks"]
        guarded = [key for key in LockKey if start.get(key.value) == locked]
        guarded = [key for key in guarded if key not in self.confirmed.locks]
        for key, pointer in _lock_pointers(self.before, self.after):
            if key in guarded and self.changed(pointer):
                self.restore(pointer)
                _append_once(self.result.locked_keys, key)
        for key in guarded:
            if final.get(key.value) != locked:
                final[key.value] = locked
                _append_once(self.result.locked_keys, key)

    def concept(self, attempted: set[str]) -> None:
        """Refuse confirmed concept edits. A pointer counts when any op wrote a
        value other than the start value (``attempted``), even if a guard or a
        later op put the start value back, and when the final result differs."""
        stage = VideoStage(self.before["stage"])
        if STAGE_ORDER.index(stage) < STAGE_ORDER.index(VideoStage.concept_confirmed):
            return
        for pointer in CONCEPT_POINTERS:
            if pointer in attempted or self.changed(pointer):
                if self.changed(pointer):
                    self.restore(pointer)
                _append_once(self.result.concept_changes, pointer)

    def record_origin(self, path: str, origin: Origin) -> None:
        """Record the origin of a settings value this op wrote.

        Nothing is recorded when a guard kept the value, or when the value did
        not change and a higher origin already owns it. A changed value replaces
        the origins of the changed values below it.
        """
        rel = path[len(SETTINGS) :]
        if not _ORIGIN_KEY.fullmatch(rel):
            return
        if any(_covers(kept, path) for kept in self.kept):
            return
        before_origins: dict[str, str] = self.before["settings"]["origins"]
        if not self.changed(path) and ORIGIN_RANK[origin] < _origin_rank(before_origins, rel):
            return
        origins: dict[str, str] = self.after["settings"]["origins"]
        for key in list(origins):
            if key != rel and _covers(rel, key) and self.changed(SETTINGS + key):
                del origins[key]
        origins[rel] = origin.value


def _concept_writes(start: dict[str, Any], doc: dict[str, Any]) -> set[str]:
    """Concept pointers whose value in ``doc`` differs from the plan start."""
    return {pointer for pointer in CONCEPT_POINTERS if _get(start, pointer) != _get(doc, pointer)}


def _append_once(items: list[Any], value: Any) -> None:
    if value not in items:
        items.append(value)


def _validated(doc: dict[str, Any]) -> Video:
    try:
        return Video.model_validate(doc)
    except ValidationError as error:
        raise AppError("invalid_op", detail={"errors": error.error_count()}) from error


def apply(
    video: Video,
    ops: Iterable[Op],
    origin_default: Origin,
    confirmed: Confirmed | None = None,
) -> Applied:
    """Apply ops in order to an in-memory video. Pure: no store is touched.

    ``origin_default`` is the highest origin the caller may record: an op that
    claims a higher origin is recorded with ``origin_default`` instead. Origins
    are guarded op by op; locks and the confirmed concept are guarded once,
    against the state the plan started from.
    """
    allowed = confirmed or Confirmed()
    result = Applied(video=video)
    start = _dump(video)
    doc = start
    attempted: set[str] = set()
    for op in ops:
        step = _Guard(doc, copy.deepcopy(doc), allowed, result)
        if isinstance(op, SetOp):
            origin = effective_origin(op.origin, origin_default)
            _check_set_path(op, origin)
            if op.path.startswith("/scenes/"):
                _scene_index(step.after, _parts(op.path)[1])
            _put(step.after, op.path, copy.deepcopy(op.value))
            attempted |= _concept_writes(start, step.after)
            if op.path.startswith(SETTINGS + "/"):
                step.origins(op.path, origin)
                step.record_origin(op.path, origin)
        else:
            _apply_structure(step.after, op)
        attempted |= _concept_writes(start, step.after)
        _validated(step.after)
        doc = step.after
    final = _Guard(start, copy.deepcopy(doc), allowed, result)
    final.concept(attempted)
    final.locks()
    result.video = _validated(final.after)
    return result


# Semantic checks (CONTRACTS 1.3)


@dataclass(frozen=True)
class _ExtraLayer:
    """The second caption language with the catalog rows it resolved to."""

    layer: CaptionLayer
    language: CaptionLanguageManifest | None
    template: Any
    primary_font: FontManifest | None
    extra_font: FontManifest | None


class _Checker:
    def __init__(self, video: Video, catalog: CatalogPort) -> None:
        self.video = video
        self.catalog = catalog
        self.issues: list[Issue] = []

    def add(self, pointer: str, code: str) -> None:
        issue = Issue(pointer=pointer, code=code)
        if issue not in self.issues:
            self.issues.append(issue)

    def lookup(self, pointer: str, kind: str, ref: PinnedRef | str | None) -> Any:
        if ref is None:
            return None
        try:
            if isinstance(ref, PinnedRef):
                return self.catalog.get(kind, ref.id, ref.revision)
            return self.catalog.get(kind, ref)
        except UnknownCatalogId:
            self.add(pointer, "unknown_catalog_id")
            return None

    def settings(self) -> tuple[Any, Any, _ExtraLayer | None]:
        s = self.video.settings
        base = f"{SETTINGS}"
        self.lookup(f"{base}/format/card_id", "format_card", s.format.card_id)
        self.lookup(f"{base}/format/story_structure", "story_structure", s.format.story_structure)
        template = self.lookup(f"{base}/format/layout", "template", s.format.layout)
        style = self.lookup(f"{base}/visual/art_style", "art_style", s.visual.art_style)
        self.lookup(f"{base}/audio/voice", "voice", s.audio.voice)
        self.lookup(f"{base}/audio/bgm/entry", "bgm", s.audio.bgm.entry)
        font = self.lookup(f"{base}/caption/font_id", "font", s.caption.font_id)
        typing = self.lookup(
            f"{base}/caption/typing_sound", "sfx", s.caption.typing_sound
        )
        if s.caption.typing_sound is not None:
            if s.caption.mode is not CaptionMode.typewriter:
                self.add(f"{base}/caption/typing_sound", "typing_sound_mode")
            if typing is not None and not isinstance(typing, TypingSoundEntry):
                self.add(f"{base}/caption/typing_sound", "typing_sound_kind")
        if template is not None and s.caption.mode is CaptionMode.typewriter:
            if not template.dialog_box:
                self.add(f"{base}/caption/mode", "typewriter_layout")
        return template, style, self.caption_extra(template, style, font)

    def caption_extra(
        self, template: Any, style: Any, primary_font: Any
    ) -> _ExtraLayer | None:
        s = self.video.settings
        if not s.caption.extra:
            return None
        layer = s.caption.extra[0]
        pointer = f"{SETTINGS}/caption/extra/0"
        language = self.lookup(f"{pointer}/language", "caption_language", layer.language)
        if layer.mode is not CaptionMode.sentence:
            self.add(f"{pointer}/mode", "caption_mode_language")
        if template is not None and (
            template.dialog_box or template.renderer.kind != "builtin"
        ):
            self.add(pointer, "caption_layer_unsupported")
        if style is not None and layer.font_id.id not in style.fonts:
            self.add(f"{pointer}/font_id", "unknown_catalog_id")
        return _ExtraLayer(
            layer=layer,
            language=language,
            template=template,
            primary_font=primary_font,
            extra_font=self.lookup(f"{pointer}/font_id", "font", layer.font_id),
        )

    def caption_line(self, pointer: str, line: Any, extra: _ExtraLayer) -> None:
        """The line needs a translation, and the position pair needs room.

        The renderer searches the actual text sizes. This check rejects only a
        position pair that cannot hold even the smallest caption blocks both
        layers may draw, so a later text edit owns any remaining collision.
        """
        translated = next(
            (
                item.text
                for item in line.extra_texts
                if item.language == extra.layer.language
            ),
            None,
        )
        if translated is None:
            self.add(f"{pointer}/extra_texts", "caption_text_missing")
            return
        template = extra.template
        if (
            template is None
            or template.dialog_box
            or template.renderer.kind != "builtin"
            or extra.primary_font is None
            or extra.extra_font is None
        ):
            return
        inner = caption_inner(template.regions.caption, dialog=False)
        pair = place_pair(
            inner,
            [smallest_caption_height(extra.primary_font.pixel_size)],
            self.video.settings.caption.position,
            [smallest_caption_height(extra.extra_font.pixel_size)],
            extra.layer.position,
        )
        if pair is None:
            self.add(pointer, "caption_overlap")

    def character(self, style: Any) -> None:
        s = self.video.settings
        role = s.format.character_role
        character = s.visual.character
        placed = any(
            scene.visual is not None and scene.visual.characters
            for scene in self.video.scenes.values()
        )
        if role is CharacterRole.none and (character is not None or placed):
            self.add(f"{SETTINGS}/format/character_role", "role_none_character")
        if role is not CharacterRole.none and character is None:
            self.add(f"{SETTINGS}/visual/character", "character_missing")
        if style is None:
            return
        if s.visual.theme_id not in {theme.id for theme in style.themes}:
            self.add(f"{SETTINGS}/visual/theme_id", "unknown_catalog_id")
        if character is None:
            return
        slots = character.slots.model_dump()
        rig_slots = style.rig.slots.model_dump()
        for slot, asset_id in slots.items():
            if asset_id is not None and asset_id not in rig_slots[slot]:
                self.add(f"{SETTINGS}/visual/character/slots/{slot}", "unknown_catalog_id")
        chosen = {value for slot, value in slots.items() if slot != "body" and value}
        for rule in style.rig.compat:
            if rule.asset_id in chosen and slots["body"] not in rule.body_ids:
                self.add(f"{SETTINGS}/visual/character/slots", "incompatible_part")

    def order(self) -> None:
        order = self.video.scene_order
        if len(set(order)) != len(order) or set(order) != set(self.video.scenes):
            self.add("/scene_order", "duplicate_order")

    def scenes(self, style: Any, extra: _ExtraLayer | None) -> None:
        seen: set[str] = set()
        backgrounds: set[str] = set()
        if style is not None:
            backgrounds = {asset.id for asset in style.assets if asset.kind == "background"}
        for scene_id, scene in self.video.scenes.items():
            base = f"/scenes/{scene_id}"
            line_ids = {line.id for line in scene.lines}
            for index, line in enumerate(scene.lines):
                if line.id in seen:
                    self.add(f"{base}/lines/{index}/id", "duplicate_line_id")
                seen.add(line.id)
                self.highlight(f"{base}/lines/{index}/highlight", line.display_text, line)
                if extra is not None:
                    self.caption_line(f"{base}/lines/{index}", line, extra)
            if scene.visual is not None:
                self.visual(base, scene, line_ids, style, backgrounds)

    def highlight(self, pointer: str, text: str, line: Any) -> None:
        end = 0
        for span in sorted(line.highlight, key=lambda item: item.start):
            if span.start >= span.end or span.end > len(text) or span.start < end:
                self.add(pointer, "highlight_range")
                return
            end = span.end

    def visual(
        self, base: str, scene: Scene, line_ids: set[str], style: Any, backgrounds: set[str]
    ) -> None:
        visual = scene.visual
        assert visual is not None
        for index, element in enumerate(visual.elements):
            if element.reveal_line_id is not None and element.reveal_line_id not in line_ids:
                self.add(f"{base}/visual/elements/{index}/reveal_line_id", "reveal_line_unknown")
        for index, cue in enumerate(visual.sfx):
            if cue.line_id not in line_ids:
                self.add(f"{base}/visual/sfx/{index}/line_id", "reveal_line_unknown")
            entry = self.lookup(
                f"{base}/visual/sfx/{index}/sfx_id", "sfx", cue.sfx_id
            )
            if isinstance(entry, TypingSoundEntry) or (
                isinstance(entry, SfxEntry) and entry.kind is SfxKind.typing
            ):
                self.add(f"{base}/visual/sfx/{index}/sfx_id", "typing_cue")
        if style is None:
            return
        if visual.background_id not in backgrounds:
            self.add(f"{base}/visual/background_id", "unknown_catalog_id")
        assets = {asset.id for asset in style.assets}
        for index, element in enumerate(visual.elements):
            if element.kind is ElementKind.asset and element.value not in assets:
                self.add(f"{base}/visual/elements/{index}/value", "unknown_catalog_id")
        for index, placement in enumerate(visual.characters):
            if placement.expression_id not in style.rig.expressions:
                self.add(f"{base}/visual/characters/{index}/expression_id", "unknown_catalog_id")
            if placement.pose_id not in style.rig.poses:
                self.add(f"{base}/visual/characters/{index}/pose_id", "unknown_catalog_id")


def validate(video: Video, catalog: CatalogPort) -> list[Issue]:
    """Semantic issues of a schema-valid video, in a stable order."""
    checker = _Checker(video, catalog)
    _, style, extra = checker.settings()
    checker.character(style)
    checker.order()
    checker.scenes(style, extra)
    return checker.issues


def new_issues(
    before: Video,
    after: Video,
    catalog: CatalogPort,
    *,
    ignore: Iterable[str] = (),
) -> list[Issue]:
    """Issues of ``after`` that ``before`` did not already have with the same value.

    An issue that existed before is tolerated only while the value at its
    pointer stays the same, so a new invalid value at an old issue's place is new.
    ``ignore`` holds codes the caller accepts at this commit. A generated script
    or scene cannot fill caption translations, so the caller keeps the layer and
    lets the user add them; ``validate`` still reports the missing text.
    """
    old = _dump(before)
    new = _dump(after)
    known = set(validate(before, catalog))
    ignored = set(ignore)
    return [
        issue
        for issue in validate(after, catalog)
        if issue.code not in ignored
        if issue not in known or _get(old, issue.pointer) != _get(new, issue.pointer)
    ]


__all__ = [
    "CONCEPT_POINTERS",
    "DEFAULT_LOCKS",
    "LOCK_POINTERS",
    "ORIGIN_RANK",
    "SOURCE_ORIGIN",
    "Applied",
    "Confirmed",
    "apply",
    "confirmed_by",
    "default_settings",
    "effective_origin",
    "language_script",
    "new_issues",
    "validate",
]
