"""Next-video snapshots and seeded, catalog-only variation.

History is ordered oldest to newest. Prefer values absent from the last two
videos; when those exhaust the catalog, avoid the newest value first. A sole
compatible candidate is retained. Backgrounds belong to scenes, not Settings,
so their lock is copied for scene generation and no scene is carried forward.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any

from app.ports import AppError, CatalogPort, UnknownCatalogId
from app.schemas.api import CreateVideoRequest
from app.schemas.common import CaptionMode, CharacterRole, Origin
from app.schemas.project import Project
from app.schemas.settings import Humor, LockKey, LockState, Register, Settings, Transition
from app.schemas.video import CreatedBy, DerivedFrom, Video, VideoStage
from app.services.project import revision, state

if TYPE_CHECKING:
    from app.services.project.service import ProjectService

# Dependencies precede their consumers. Shared lock pointers remain owned by state.
_KEYS = (
    LockKey.art_style, LockKey.layout, LockKey.character_role, LockKey.character,
    LockKey.theme, LockKey.caption_mode, LockKey.caption_font, LockKey.voice,
    LockKey.story_structure, LockKey.register, LockKey.humor, LockKey.bgm,
    LockKey.transition,
)

_SEARCH_BUDGET = 1500
"""Most candidate checks one derivation may make. A catalog with no valid
combination fails fast instead of walking every product of the varied keys."""


class _Exhausted(Exception):
    """The search budget ran out before a valid combination was found."""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _value(settings: Settings, key: LockKey) -> Any:
    node = settings.model_dump(mode="json", by_alias=True)
    for part in state.LOCK_POINTERS[key].split("/")[2:]:
        node = node[part]
    return node


def _identity(key: LockKey, value: Any) -> str:
    if key is LockKey.bgm:
        value = value["entry"] or value["mood"]
    if key is LockKey.character and value is not None:
        value = value["slots"]
    if isinstance(value, dict) and set(value) == {"id", "revision"}:
        value = value["id"]
    return _json(value)


def _replace(settings: Settings, key: LockKey, value: Any) -> Settings:
    doc = settings.model_dump(mode="json", by_alias=True)
    parts = state.LOCK_POINTERS[key].split("/")[2:]
    node = doc
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value
    pointer = "/" + "/".join(parts)
    origins = doc["origins"]
    for old in list(origins):
        if old.startswith(pointer + "/"):
            del origins[old]
    origins[pointer] = Origin.derived.value
    return Settings.model_validate(doc)


def _snapshot(project: Project, settings: Settings, video_id: str) -> Video:
    return Video(
        schema_version=1, id=video_id, project_id=project.id, owner_id=project.owner_id,
        revision=1, parent_revision=None, created_at=revision.now(),
        created_by=CreatedBy.create, change_id=None, stage=VideoStage.draft,
        derived_from=None, topic="", material=[], reference=None, settings=settings,
        script=None, scene_order=[], scenes={},
    )


class _Picker:
    def __init__(
        self, catalog: CatalogPort, project: Project, previous: list[Video],
        seed: int, base: Settings,
    ) -> None:
        self.catalog = catalog
        self.previous = previous[-2:]
        self.seed = seed
        self.probe = _snapshot(project, base, project.id)
        self.keys = [key for key in _KEYS if base.locks.get(key) is LockState.varied]
        self.budget = _SEARCH_BUDGET

    def rank(self, key: str, value: Any) -> bytes:
        return hashlib.sha256(_json([self.seed, key, value]).encode()).digest()

    def refs(self, kind: str) -> list[dict[str, str]]:
        return [
            self.catalog.pin(kind, item.id).model_dump(mode="json")
            for item in sorted(self.catalog.list(kind), key=lambda item: item.id)
        ]

    def style(self, settings: Settings) -> Any:
        ref = settings.visual.art_style
        return self.catalog.get("art_style", ref.id, ref.revision)

    def template(self, settings: Settings) -> Any:
        ref = settings.format.layout
        return self.catalog.get("template", ref.id, ref.revision)

    def characters(self, settings: Settings) -> Iterator[Any]:
        if settings.format.character_role is CharacterRole.none:
            yield None
            return
        rig = self.style(settings).rig
        names = tuple(type(rig.slots).model_fields)
        choices = []
        for name in names:
            values = getattr(rig.slots, name)
            values = values if name in ("body", "face") else [None, *values]
            choices.append(sorted(values, key=lambda value: self.rank(name, value)))
        for values in itertools.product(*choices):
            slots = dict(zip(names, values, strict=True))
            if all(
                rule.asset_id not in values or slots["body"] in rule.body_ids
                for rule in rig.compat
            ):
                yield {"preset_id": None, "slots": slots}

    def bgms(self, settings: Settings) -> list[Any]:
        base = settings.audio.bgm.model_dump(mode="json")
        entries = self.refs("bgm")
        return [
            {**base, "entry": ref, "mood": self.catalog.get("bgm", ref["id"]).mood.value}
            for ref in entries
        ] or [base]

    def options(self, key: LockKey, s: Settings) -> Iterable[Any]:
        if key is LockKey.character:
            return self.characters(s)
        if key is LockKey.bgm:
            return self.bgms(s)
        if key is LockKey.theme:
            return [theme.id for theme in self.style(s).themes]
        if key is LockKey.character_role:
            roles = self.style(s).capabilities.character_roles
            return list(dict.fromkeys([CharacterRole.none.value, *[r.value for r in roles]]))
        if key is LockKey.caption_mode:
            return [mode.value for mode in self.style(s).capabilities.caption_modes]
        kinds = {
            LockKey.art_style: "art_style", LockKey.layout: "template",
            LockKey.voice: "voice", LockKey.caption_font: "font",
        }
        if key in kinds:
            return self.refs(kinds[key])
        if key is LockKey.story_structure:
            return [item.id for item in self.catalog.list("story_structure")]
        enums = {LockKey.register: Register, LockKey.humor: Humor, LockKey.transition: Transition}
        return [value.value for value in enums[key]]

    def ordered(self, key: LockKey, s: Settings) -> Iterator[Any]:
        old = [_identity(key, _value(video.settings, key)) for video in self.previous]
        current = _value(s, key)
        # Character products stay lazy; only the small per-slot domains are sorted.
        options = None if key is LockKey.character else sorted(
            self.options(key, s), key=lambda value: self.rank(key.value, value)
        )
        for tier in range(3):
            domain = self.characters(s) if options is None else options
            for value in domain:
                identity = _identity(key, value)
                priority = 0 if identity not in old else (1 if identity != old[-1] else 2)
                if priority == tier:
                    yield current if identity == _identity(key, current) else value

    def problems(self, s: Settings) -> list[str]:
        self.budget -= 1
        if self.budget < 0:
            raise _Exhausted
        video = self.probe.model_copy(update={"settings": s})
        problems = [issue.pointer for issue in state.validate(video, self.catalog)]
        style, template = self.style(s), self.template(s)
        font = self.catalog.get("font", s.caption.font_id.id, s.caption.font_id.revision)
        voice = self.catalog.get("voice", s.audio.voice.id, s.audio.voice.revision)
        mode = s.caption.mode
        checks = (
            (s.format.layout.id not in style.capabilities.layouts,
             (LockKey.art_style, LockKey.layout)),
            (s.format.character_role is not CharacterRole.none
             and s.format.character_role not in style.capabilities.character_roles,
             (LockKey.art_style, LockKey.character_role)),
            (mode not in style.capabilities.caption_modes or mode not in template.caption_modes
             or (mode is CaptionMode.typewriter and not template.dialog_box),
             (LockKey.art_style, LockKey.layout, LockKey.caption_mode)),
            (s.caption.font_id.id not in style.fonts
             or state.FONT_SCRIPT[s.language] not in [script.value for script in font.scripts],
             (LockKey.art_style, LockKey.caption_font)),
            (s.language not in voice.languages, (LockKey.voice,)),
        )
        # Preference checks bind only values the picker chooses. A copied pair is
        # judged by the shared semantic checks alone, so a valid source always
        # derives. The latest varied key in search order owns the problem.
        for bad, keys in checks:
            chosen = [key for key in self.keys if key in keys]
            if bad and chosen:
                problems.append(state.LOCK_POINTERS[chosen[-1]])
        return problems

    def search(self, s: Settings, index: int = 0) -> Settings | None:
        if index == len(self.keys):
            return s if not self.problems(s) else None
        key = self.keys[index]
        pending = [state.LOCK_POINTERS[key] for key in self.keys[index + 1:]]
        for value in self.ordered(key, s):
            candidate = s if value == _value(s, key) else _replace(s, key, value)
            if (key is LockKey.character_role and value == CharacterRole.none.value
                    and LockKey.character in self.keys[index + 1:]
                    and candidate.visual.character is not None):
                # The character is still to be chosen; with no role it can only be none.
                candidate = _replace(candidate, LockKey.character, None)
            if any(
                not any(problem == path or problem.startswith(path + "/") for path in pending)
                for problem in self.problems(candidate)
            ):
                continue
            result = self.search(candidate, index + 1)
            if result is not None:
                return result
        return None


def pick_varied(
    catalog: CatalogPort, project: Project, previous: list[Video], seed: int,
    *, settings: Settings | None = None,
) -> Settings:
    """Copy the supplied snapshot (or newest history/defaults) and vary only opted-in keys."""
    if any(
        video.project_id != project.id or video.owner_id != project.owner_id
        for video in previous
    ):
        raise AppError("not_found")
    base = settings if settings is not None else (
        previous[-1].settings if previous else project.defaults
    )
    base = base.model_copy(deep=True)
    try:
        result = _Picker(catalog, project, previous, seed, base).search(base)
    except UnknownCatalogId as error:
        raise AppError("unknown_catalog_id") from error
    except _Exhausted:
        result = None
    if result is None:
        # A missing registry id is reported as such, not as a combination failure.
        probe = _snapshot(project, base, project.id)
        codes = {issue.code for issue in state.validate(probe, catalog)}
        raise AppError(
            "unknown_catalog_id" if "unknown_catalog_id" in codes else "invalid_combination"
        )
    return result


def create_video(service: ProjectService, project_id: str, req: CreateVideoRequest) -> Video:
    """Prepare a revision-one snapshot for the existing creation write path."""
    project = service.projects.get_project(project_id)
    source = None
    settings = project.defaults.model_copy(deep=True)
    if req.from_video_id is not None:
        source = service.projects.get_video(req.from_video_id)
        if source.project_id != project.id or source.owner_id != project.owner_id:
            raise AppError("not_found")
        previous = [service.projects.get_video(video_id) for video_id in project.video_ids[-2:]]
        settings = pick_varied(
            service.catalog, project, previous, len(project.video_ids), settings=source.settings
        )
    if req.preset_id is not None:
        from app.services.project import presets

        preset = presets.get_preset(service, project.id, req.preset_id)
        settings = presets.settings_for(settings, preset, preserve_existing=source is not None)
    video = _snapshot(project, settings, service.projects.new_id("v"))
    if source is not None:
        video = video.model_copy(update={
            "created_by": CreatedBy.next_video,
            "derived_from": DerivedFrom(video_id=source.id, revision=source.revision),
        })
    return video
