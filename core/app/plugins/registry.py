"""Manifest registry: the only loader of builtin and generated catalog packages.

The registry reads data files only. It never imports or executes code from a
package, and it rejects an item before registration when a rule fails. Code BGM
packages validate both WAV and program digests and share the immutable package
storage and persistent index used by generated styles and templates.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.caption_layout import caption_region_fits
from app.ports import UnknownCatalogId, canonical_digest
from app.schemas.api import CatalogItem, CatalogKind, Compatibility
from app.schemas.bgm_entry import BuiltinBgm, CodeBgm, SfxEntry, TypingSoundEntry, UploadBgm
from app.schemas.caption_language_manifest import CaptionLanguageManifest
from app.schemas.caption_style_manifest import CaptionStyleManifest
from app.schemas.common import (
    PERSONAL_OWNER_ID,
    Language,
    LocalizedText,
    PackageOrigin,
    PinnedRef,
)
from app.schemas.font_manifest import FontManifest, FontScript
from app.schemas.format_card import FormatCard, StoryStructure
from app.schemas.style_manifest import StyleManifest
from app.schemas.template_manifest import TemplateManifest
from app.schemas.video import Video
from app.schemas.voice_manifest import VoiceManifest

INDEX_VERSION = 1
ARCHIVE_DIR = "c"
INDEX_RELATIVE = ("catalog", "index.json")

PACKAGE_DIRS = {
    "art_style": "art_styles",
    "caption_style": "caption_styles",
    "template": "templates",
    "voice": "voices",
    "bgm": "bgm",
    "sfx": "sfx",
    "font": "fonts",
}
FILE_DIRS = {
    "format_card": "format_cards",
    "story_structure": "story_structures",
    "caption_language": "caption_languages",
}
MODELS: dict[str, type[BaseModel]] = {
    "art_style": StyleManifest,
    "caption_style": CaptionStyleManifest,
    "template": TemplateManifest,
    "voice": VoiceManifest,
    "bgm": BuiltinBgm,
    "sfx": SfxEntry,
    "font": FontManifest,
    "format_card": FormatCard,
    "story_structure": StoryStructure,
    "caption_language": CaptionLanguageManifest,
}


def _manifest_model(kind: str, raw: Any) -> type[BaseModel]:
    """Use the same BGM source and sfx keys discriminator for loading and restore."""
    if kind == "bgm" and isinstance(raw, dict):
        if raw.get("source") == "code":
            return CodeBgm
        if raw.get("source") == "upload":
            return UploadBgm
    if kind == "sfx" and isinstance(raw, dict) and "keys" in raw:
        return TypingSoundEntry
    return MODELS[kind]


class RegistryError(Exception):
    """A package failed validation. The item is rejected before registration."""

    def __init__(self, code: str, item: str, path: Path, detail: str = "") -> None:
        self.code = code
        self.item = item
        self.path = path
        self.detail = detail
        message = f"{code}: {item} at {path}"
        super().__init__(f"{message} ({detail})" if detail else message)


@dataclass(frozen=True)
class Entry:
    kind: str
    id: str
    revision: str
    label: LocalizedText
    origin: PackageOrigin
    manifest: BaseModel
    package_dir: Path


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _referenced_files(manifest: BaseModel) -> list[str]:
    if isinstance(manifest, (StyleManifest, TemplateManifest, VoiceManifest, FontManifest)):
        return _style_like_files(manifest)
    if isinstance(manifest, CaptionStyleManifest):
        return [manifest.renderer.program]
    if isinstance(manifest, TypingSoundEntry):
        return [key.file for key in manifest.keys] + [manifest.license.license_file]
    if isinstance(manifest, (BuiltinBgm, SfxEntry)):
        return [manifest.file, manifest.license.license_file]
    if isinstance(manifest, UploadBgm):
        return [manifest.file]
    if isinstance(manifest, CodeBgm):
        return [manifest.file, manifest.program]
    return []


def _style_like_files(
    manifest: StyleManifest | TemplateManifest | VoiceManifest | FontManifest,
) -> list[str]:
    files: list[str] = []
    if isinstance(manifest, StyleManifest):
        files.extend(asset.file for asset in manifest.assets)
        files.extend(license.license_file for license in manifest.licenses.values())
        if manifest.preview is not None:
            files.append(manifest.preview)
        if manifest.renderer.kind == "sandbox":
            files.append(manifest.renderer.program)
    elif isinstance(manifest, TemplateManifest):
        files.append(manifest.test.scene)
        if manifest.renderer.kind == "sandbox":
            files.append(manifest.renderer.program)
    elif isinstance(manifest, VoiceManifest):
        files.append(manifest.sample.file)
        files.append(manifest.license.license_file)
    elif isinstance(manifest, FontManifest):
        files.append(manifest.file)
        files.append(manifest.license.license_file)
    return sorted(set(files))


def _digest_files(manifest: BaseModel) -> list[tuple[str, str]]:
    if isinstance(manifest, StyleManifest):
        files = [(asset.file, asset.sha256) for asset in manifest.assets]
        if manifest.renderer.kind == "sandbox":
            files.append(
                (manifest.renderer.program, manifest.renderer.program_digest)
            )
        return files
    if isinstance(manifest, TemplateManifest):
        if manifest.renderer.kind == "sandbox":
            return [
                (manifest.renderer.program, manifest.renderer.program_digest)
            ]
        return []
    if isinstance(manifest, CaptionStyleManifest):
        return [(manifest.renderer.program, manifest.renderer.program_digest)]
    if isinstance(manifest, VoiceManifest):
        return [(manifest.sample.file, manifest.sample.sha256)]
    if isinstance(manifest, FontManifest):
        return [(manifest.file, manifest.sha256)]
    if isinstance(manifest, UploadBgm):
        return [(manifest.file, manifest.sha256)]
    if isinstance(manifest, CodeBgm):
        return [
            (manifest.file, manifest.sha256),
            (manifest.program, manifest.program_digest),
        ]
    if isinstance(manifest, TypingSoundEntry):
        return [(key.file, key.sha256) for key in manifest.keys]
    if isinstance(manifest, (BuiltinBgm, SfxEntry)):
        return [(manifest.file, manifest.sha256)]
    return []


def _check_package_path(root: Path, path: Path, item_id: str) -> None:
    """Reject symlinked packages before reading a manifest from outside the root."""
    try:
        relative = path.parent.relative_to(root)
    except ValueError as error:
        raise RegistryError("path_escape", item_id, path) from error
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RegistryError("path_escape", item_id, current)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise RegistryError("path_escape", item_id, path)


def _resolve(package_dir: Path, relative: str, item: str) -> Path:
    candidate = package_dir / relative
    if candidate.is_symlink():
        raise RegistryError("path_escape", item, candidate, "symlink is not allowed")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(package_dir.resolve()):
        raise RegistryError("path_escape", item, candidate)
    if not resolved.is_file():
        raise RegistryError("missing_file", item, candidate)
    return resolved


def file_list_revision(package_dir: Path) -> str:
    """Canonical SHA-256 of every regular file in the package, path sorted."""
    files: list[dict[str, str]] = []
    for path in sorted(package_dir.rglob("*"), key=lambda p: p.relative_to(package_dir).as_posix()):
        relative = path.relative_to(package_dir).as_posix()
        if path.is_symlink():
            raise RegistryError("path_escape", package_dir.name, path, "symlink is not allowed")
        if path.is_file():
            files.append({"path": relative, "sha256": _sha256(path)})
    return canonical_digest({"files": files})


def validate_package(
    kind: str,
    package_dir: Path,
    expected_id: str,
    raw: dict[str, Any],
) -> BaseModel:
    """Validate one manifest and its files. Raises RegistryError before registration."""
    model_type = _manifest_model(kind, raw)
    if raw.get("schema_version") != 1:
        raise RegistryError("unsupported_version", expected_id, package_dir, "schema_version")
    if kind in ("art_style", "caption_style", "template") and raw.get("api_version") != 1:
        raise RegistryError("unsupported_version", expected_id, package_dir, "api_version")
    try:
        manifest = model_type.model_validate(raw)
    except ValidationError as error:
        raise RegistryError(
            "invalid_manifest", expected_id, package_dir, str(error)
        ) from error

    if manifest.id != expected_id:  # type: ignore[attr-defined]
        raise RegistryError("id_mismatch", expected_id, package_dir, manifest.id)  # type: ignore[attr-defined]

    for relative in _referenced_files(manifest):
        _resolve(package_dir, relative, expected_id)
    for relative, expected in _digest_files(manifest):
        actual = _sha256(_resolve(package_dir, relative, expected_id))
        if actual != expected:
            raise RegistryError("digest_mismatch", expected_id, package_dir / relative)

    if isinstance(manifest, TemplateManifest):
        if not caption_region_fits(manifest):
            raise RegistryError(
                "unsafe_caption_box", expected_id, package_dir / "manifest.json"
            )
    return manifest


def _listed_for(manifest: BaseModel, video: Video | None) -> bool:
    """An upload shows only to its owner, and with a video only in that video's project."""
    if not isinstance(manifest, UploadBgm):
        return True
    if manifest.owner_id != PERSONAL_OWNER_ID:
        return False
    return video is None or manifest.project_id == video.project_id


def _compatibility(
    entry: Entry, video: Video, language_script: FontScript | None
) -> Compatibility | None:
    manifest = entry.manifest
    settings = video.settings
    if isinstance(manifest, TemplateManifest):
        if settings.caption.mode not in manifest.caption_modes:
            return Compatibility(ok=False, reason="error.catalog.caption_mode")
        if settings.caption.mode == "typewriter" and not manifest.dialog_box:
            return Compatibility(ok=False, reason="error.catalog.dialog_box")
        if settings.format.layout.id != manifest.id:
            return Compatibility(ok=False, reason="error.catalog.layout")
        return Compatibility(ok=True, reason=None)
    if isinstance(manifest, StyleManifest):
        if settings.visual.art_style.id != manifest.id:
            return Compatibility(ok=False, reason="error.catalog.art_style")
        if settings.caption.mode not in manifest.capabilities.caption_modes:
            return Compatibility(ok=False, reason="error.catalog.caption_mode")
        if settings.format.character_role not in manifest.capabilities.character_roles:
            return Compatibility(ok=False, reason="error.catalog.character_role")
        return Compatibility(ok=True, reason=None)
    if isinstance(manifest, FontManifest):
        if language_script is None:
            return None
        if language_script not in manifest.scripts:
            return Compatibility(ok=False, reason="error.catalog.font_scripts")
        return Compatibility(ok=True, reason=None)
    return None


class Registry:
    """CatalogPort implementation over the fixed plugin and catalog roots."""

    def __init__(
        self,
        plugin_root: Path | None = None,
        catalog_root: Path | None = None,
        data_dir: Path | None = None,
    ) -> None:
        default = Path(__file__).resolve().parent
        self.plugin_root = plugin_root or default
        self.catalog_root = catalog_root or default.parent / "catalog"
        self.data_dir = data_dir
        self._entries: dict[tuple[str, str], Entry] = {}
        self._generated: dict[tuple[str, str], Entry] = {}
        self._pinned: dict[tuple[str, str, str], Entry] = {}
        self._index: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._loaded = False
        self._lock = threading.RLock()

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            for kind, subdir in PACKAGE_DIRS.items():
                self._scan_directories(kind, self.plugin_root / subdir, "manifest.json")
            for kind, subdir in FILE_DIRS.items():
                self._scan_directories(kind, self.catalog_root / subdir, None)
            self._restore_index()
            self._loaded = True

    def _scan_directories(self, kind: str, root: Path, manifest_name: str | None) -> None:
        if root.is_symlink():
            raise RegistryError("path_escape", kind, root, "symlink is not allowed")
        if not root.is_dir():
            return
        paths = sorted(root.glob("*/manifest.json" if manifest_name else "*.json"))
        for path in paths:
            item_id = path.parent.name if manifest_name else path.stem
            _check_package_path(root, path, item_id)
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise RegistryError("invalid_manifest", item_id, path, str(error)) from error
            if not isinstance(raw, dict):
                raise RegistryError("invalid_manifest", item_id, path)
            manifest = validate_package(kind, path.parent, item_id, raw)
            key = (kind, item_id)
            if key in self._entries:
                raise RegistryError("duplicate_id", item_id, path)
            if manifest_name:
                revision = file_list_revision(path.parent)
            else:
                revision = canonical_digest(
                    {"files": [{"path": path.name, "sha256": _sha256(path)}]}
                )
            self._entries[key] = Entry(
                kind=kind,
                id=item_id,
                revision=revision,
                label=manifest.label,  # type: ignore[attr-defined]
                origin=getattr(manifest, "origin", PackageOrigin.builtin),
                manifest=manifest,
                package_dir=path.parent,
            )

    def _index_path(self) -> Path | None:
        if self.data_dir is None:
            return None
        return self.data_dir.joinpath(*INDEX_RELATIVE)

    def _relative_path(self, path: Path) -> str:
        assert self.data_dir is not None
        return path.resolve().relative_to(self.data_dir.resolve()).as_posix()

    def _record(self, entry: Entry) -> dict[str, Any]:
        return {
            "kind": entry.kind,
            "id": entry.id,
            "revision": entry.revision,
            "path": self._relative_path(entry.package_dir),
            "origin": entry.origin.value,
            "manifest": entry.manifest.model_dump(mode="json", by_alias=True),
        }

    def _write_index(self) -> None:
        path = self._index_path()
        if path is None:
            return
        payload = {
            "schema_version": INDEX_VERSION,
            "entries": [self._index[key] for key in sorted(self._index)],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def _restore_index(self) -> None:
        path = self._index_path()
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RegistryError("invalid_index", "catalog", path, str(error)) from error
        if not isinstance(payload, dict) or payload.get("schema_version") != INDEX_VERSION:
            raise RegistryError("unsupported_version", "catalog", path, "schema_version")
        assert self.data_dir is not None
        root = self.data_dir.resolve()
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise RegistryError("invalid_index", "catalog", path, "entries")
        for record in entries:
            if not isinstance(record, dict):
                raise RegistryError("invalid_index", "catalog", path, "entry")
            kind = record.get("kind")
            item_id = record.get("id")
            revision = record.get("revision")
            relative = record.get("path")
            if kind not in PACKAGE_DIRS or not isinstance(item_id, str):
                raise RegistryError("invalid_index", "catalog", path, str(kind))
            if not isinstance(relative, str) or not isinstance(revision, str):
                raise RegistryError("invalid_index", str(item_id), path)
            package = (self.data_dir / relative).resolve()
            if not package.is_relative_to(root) or package.is_symlink():
                raise RegistryError("path_escape", str(item_id), path)
            try:
                raw = record.get("manifest")
                manifest = _manifest_model(kind, raw).model_validate(raw)
            except ValidationError as error:
                raise RegistryError(
                    "invalid_manifest", str(item_id), path, str(error)
                ) from error
            entry = Entry(
                kind=kind,
                id=item_id,
                revision=revision,
                label=manifest.label,  # type: ignore[attr-defined]
                origin=PackageOrigin(record.get("origin", PackageOrigin.generated.value)),
                manifest=manifest,
                package_dir=package,
            )
            key = (kind, item_id, revision)
            self._pinned[key] = entry
            self._index[key] = record
            if entry.origin is PackageOrigin.generated:
                self._generated[(kind, item_id)] = entry

    def _archive(self, entry: Entry) -> None:
        """Keep an immutable copy of a referenced builtin revision."""
        if self.data_dir is None or entry.kind in FILE_DIRS:
            return
        key = (entry.kind, entry.id, entry.revision)
        with self._lock:
            if key in self._pinned:
                return
            target = (self.data_dir / ARCHIVE_DIR / entry.revision[:16]).resolve()
            root = self.data_dir.resolve()
            if not target.is_relative_to(root):
                raise RegistryError("path_escape", entry.id, target)
            if target.exists():
                if file_list_revision(target) != entry.revision:
                    raise RegistryError("digest_mismatch", entry.id, target)
            else:
                if file_list_revision(entry.package_dir) != entry.revision:
                    raise RegistryError("digest_mismatch", entry.id, entry.package_dir)
                staged = target.with_name(f".{target.name}.tmp")
                if staged.exists():
                    shutil.rmtree(staged)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(entry.package_dir, staged)
                if file_list_revision(staged) != entry.revision:
                    shutil.rmtree(staged)
                    raise RegistryError("digest_mismatch", entry.id, staged)
                os.replace(staged, target)
            archived = Entry(
                kind=entry.kind,
                id=entry.id,
                revision=entry.revision,
                label=entry.label,
                origin=entry.origin,
                manifest=entry.manifest,
                package_dir=target,
            )
            self._pinned[key] = archived
            self._index[key] = self._record(archived)
            self._write_index()

    def _entry_for(self, kind: str, item_id: str) -> Entry:
        self.load()
        entry = self._entries.get((kind, item_id)) or self._generated.get((kind, item_id))
        if entry is None:
            raise UnknownCatalogId(f"{kind}:{item_id}")
        return entry

    def _language_script(self, language: Language) -> FontScript | None:
        """The font script a language catalog row needs, when that row exists."""
        entry = self._entries.get(("caption_language", language.value))
        if entry is None or not isinstance(entry.manifest, CaptionLanguageManifest):
            return None
        return entry.manifest.script

    def list(self, kind: str, *, video: Video | None = None) -> list[CatalogItem]:
        if kind not in MODELS:
            raise UnknownCatalogId(kind)
        self.load()
        entries = {
            **{key: value for key, value in self._entries.items() if key[0] == kind},
            **{key: value for key, value in self._generated.items() if key[0] == kind},
        }
        script = (
            self._language_script(video.settings.language) if video is not None else None
        )
        items = []
        for _, entry in sorted(entries.items()):
            if not _listed_for(entry.manifest, video):
                continue
            items.append(
                CatalogItem(
                    kind=CatalogKind(kind),
                    id=entry.id,
                    revision=entry.revision,
                    label=entry.label,
                    origin=entry.origin,
                    thumbnail=None,
                    compatible=(
                        _compatibility(entry, video, script)
                        if video is not None
                        else None
                    ),
                )
            )
        return items

    def get(self, kind: str, item_id: str, revision: str | None = None) -> BaseModel:
        if revision is None:
            return self._entry_for(kind, item_id).manifest
        self.load()
        entry = self._pinned.get((kind, item_id, revision))
        if entry is None:
            current = self._entries.get((kind, item_id)) or self._generated.get(
                (kind, item_id)
            )
            if current is None or current.revision != revision:
                raise UnknownCatalogId(f"{kind}:{item_id}@{revision}")
            entry = current
        return entry.manifest

    def pin(self, kind: str, item_id: str) -> PinnedRef:
        entry = self._entry_for(kind, item_id)
        with self._lock:
            self._archive(entry)
        return PinnedRef(id=entry.id, revision=entry.revision)

    def package_dir(self, kind: str, ref: PinnedRef) -> Path:
        self.load()
        current = self._entries.get((kind, ref.id)) or self._generated.get((kind, ref.id))
        if current is not None and current.revision == ref.revision:
            return current.package_dir
        entry = self._pinned.get((kind, ref.id, ref.revision))
        if entry is None:
            raise UnknownCatalogId(f"{kind}:{ref.id}@{ref.revision}")
        return entry.package_dir

    def register_generated(self, kind: str, staged_dir: Path) -> PinnedRef:
        if kind not in ("art_style", "caption_style", "template", "bgm"):
            raise ValueError(f"generated packages are not supported for {kind}")
        if self.data_dir is None:
            raise RuntimeError("registry has no data directory")
        if staged_dir.is_symlink():
            raise RegistryError(
                "path_escape", staged_dir.name, staged_dir, "symlink is not allowed"
            )
        manifest_path = staged_dir / "manifest.json"
        if not manifest_path.is_file():
            raise RegistryError("missing_file", staged_dir.name, manifest_path)
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RegistryError("invalid_manifest", staged_dir.name, manifest_path)
        if kind == "bgm" and raw.get("source") not in ("code", "upload"):
            raise RegistryError("invalid_manifest", staged_dir.name, manifest_path, "source")
        manifest = validate_package(kind, staged_dir, staged_dir.name, raw)
        revision = file_list_revision(staged_dir)
        item_id = manifest.id  # type: ignore[attr-defined]
        with self._lock:
            self.load()
            if (kind, item_id) in self._entries:
                raise RegistryError("duplicate_id", item_id, staged_dir)
            existing = self._generated.get((kind, item_id))
            if existing is not None:
                if existing.revision == revision:
                    return PinnedRef(id=item_id, revision=revision)
                raise RegistryError("duplicate_id", item_id, staged_dir)
        target = self.data_dir / "s" / revision[:16]
        target_root = self.data_dir.resolve()
        if target.is_symlink() or not target.parent.resolve().is_relative_to(
            target_root
        ):
            raise RegistryError("path_escape", item_id, target)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged_dir), str(target))
        if target.is_symlink() or not target.resolve().is_relative_to(target_root):
            raise RegistryError("path_escape", item_id, target)
        if file_list_revision(target) != revision:
            raise RegistryError("digest_mismatch", item_id, target)
        entry = Entry(
            kind=kind,
            id=item_id,
            revision=revision,
            label=manifest.label,  # type: ignore[attr-defined]
            origin=getattr(manifest, "origin", PackageOrigin.generated),
            manifest=manifest,
            package_dir=target,
        )
        with self._lock:
            self._generated[(kind, entry.id)] = entry
            self._pinned[(kind, entry.id, revision)] = entry
            self._index[(kind, entry.id, revision)] = self._record(entry)
            self._write_index()
        return PinnedRef(id=entry.id, revision=revision)
