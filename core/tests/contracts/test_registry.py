"""Registry validation rejects a package before registration."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from app.plugins.registry import Registry, RegistryError, file_list_revision
from app.schemas.bgm_entry import SfxEntry, TypingSoundEntry
from app.schemas.caption_language_manifest import CaptionLanguageManifest
from app.schemas.font_manifest import FontScript

PLUGINS = Path(__file__).resolve().parents[2] / "app" / "plugins"


def _copy_package(tmp_path: Path, kind_dir: str, item: str) -> Path:
    source = PLUGINS / kind_dir / item
    target = tmp_path / kind_dir / item
    shutil.copytree(source, target)
    return target


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _registry(tmp_path: Path) -> Registry:
    return Registry(
        plugin_root=tmp_path,
        catalog_root=tmp_path / "catalog",
        data_dir=tmp_path / "data",
    )


def test_builtin_catalog_loads() -> None:
    registry = Registry()
    registry.load()
    assert {item.id for item in registry.list("template")} == {
        "fixed_stage",
        "full_stage",
        "dialog_stage",
    }


def test_caption_language_catalog_loads_scripts() -> None:
    registry = Registry()
    registry.load()

    assert {item.id for item in registry.list("caption_language")} == {"en", "ko"}
    ko = registry.get("caption_language", "ko")
    en = registry.get("caption_language", "en")
    assert isinstance(ko, CaptionLanguageManifest)
    assert isinstance(en, CaptionLanguageManifest)
    assert (ko.script, en.script) == (FontScript.hangul, FontScript.latin)
    assert registry.pin("caption_language", "ko").revision


def test_unsupported_manifest_version_is_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "art_styles", "pixel")
    manifest = _read(package / "manifest.json")
    manifest["schema_version"] = 2
    _write(package / "manifest.json", manifest)
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "unsupported_version"


def test_missing_asset_file_is_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "art_styles", "pixel")
    (package / "sprites" / "body_hero.json").unlink()
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "missing_file"


def test_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "art_styles", "pixel")
    sprite = package / "sprites" / "body_hero.json"
    sprite.write_bytes(sprite.read_bytes() + b" ")
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "digest_mismatch"


def test_caption_box_outside_safe_area_is_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "templates", "fixed_stage")
    manifest = _read(package / "manifest.json")
    manifest["regions"]["caption"]["y"] = 900
    _write(package / "manifest.json", manifest)
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "unsafe_caption_box"


def test_dialog_caption_that_cannot_fit_its_bubble_is_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "templates", "dialog_stage")
    manifest = _read(package / "manifest.json")
    manifest["regions"]["caption"].update({"y": 1040, "h": 170})
    _write(package / "manifest.json", manifest)
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "unsafe_caption_box"


def test_picture_that_does_not_cover_the_visual_region_is_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "templates", "fixed_stage")
    manifest = _read(package / "manifest.json")
    manifest["picture"]["h"] = 600
    _write(package / "manifest.json", manifest)
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "invalid_manifest"


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "art_styles", "pixel")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    sprite = package / "sprites" / "body_hero.json"
    sprite.unlink()
    try:
        os.symlink(outside, sprite)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this host")
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "path_escape"


def test_generated_package_cannot_shadow_a_builtin_id(tmp_path: Path) -> None:
    package = tmp_path / "staged" / "pixel"
    shutil.copytree(PLUGINS / "art_styles" / "pixel", package)
    manifest = _read(package / "manifest.json")
    manifest["origin"] = "generated"
    _write(package / "manifest.json", manifest)
    registry = Registry(data_dir=tmp_path / "data")
    with pytest.raises(RegistryError) as error:
        registry.register_generated("art_style", package)
    assert error.value.code == "duplicate_id"


def test_renderer_program_digest_is_checked(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "templates", "fixed_stage")
    manifest = _read(package / "manifest.json")
    manifest["renderer"] = {
        "kind": "sandbox",
        "program": "renderer.py",
        "program_digest": "0" * 64,
        "runtime_digest": "0" * 64,
        "entry": "render_layer",
        "max_ms_per_scene": 1000,
    }
    _write(package / "manifest.json", manifest)
    (package / "renderer.py").write_text("def render_layer():\n    return b''\n")
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "digest_mismatch"


def test_symlinked_package_directory_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "fixed_stage"
    shutil.copytree(PLUGINS / "templates" / "fixed_stage", outside)
    plugin_root = tmp_path / "plugins"
    (plugin_root / "templates").mkdir(parents=True)
    try:
        os.symlink(outside, plugin_root / "templates" / "fixed_stage")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this host")
    registry = Registry(plugin_root=plugin_root, catalog_root=tmp_path / "catalog")
    with pytest.raises(RegistryError) as error:
        registry.load()
    assert error.value.code == "path_escape"


def test_symlinked_kind_directory_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside_templates"
    shutil.copytree(PLUGINS / "templates", outside)
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    try:
        os.symlink(outside, plugin_root / "templates")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this host")
    registry = Registry(plugin_root=plugin_root, catalog_root=tmp_path / "catalog")
    with pytest.raises(RegistryError) as error:
        registry.load()
    assert error.value.code == "path_escape"


def test_pinned_builtin_revision_survives_a_package_update(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    shutil.copytree(PLUGINS / "templates", plugin_root / "templates")
    data_dir = tmp_path / "data"
    first = Registry(
        plugin_root=plugin_root, catalog_root=tmp_path / "catalog", data_dir=data_dir
    )
    first.load()
    ref = first.pin("template", "fixed_stage")

    package = plugin_root / "templates" / "fixed_stage"
    (package / "extra.txt").write_text("changed", encoding="utf-8")

    restarted = Registry(
        plugin_root=plugin_root, catalog_root=tmp_path / "catalog", data_dir=data_dir
    )
    restarted.load()
    current = restarted.pin("template", "fixed_stage")
    assert current.revision != ref.revision
    archived = restarted.package_dir("template", ref)
    assert archived.name == ref.revision[:16]
    assert file_list_revision(archived) == ref.revision
    assert restarted.get("template", "fixed_stage", ref.revision).id == "fixed_stage"


def test_generated_package_resolves_after_restart(tmp_path: Path) -> None:
    staged = tmp_path / "staged" / "pixel_generated"
    shutil.copytree(PLUGINS / "art_styles" / "pixel", staged)
    manifest = _read(staged / "manifest.json")
    manifest["id"] = "pixel_generated"
    manifest["origin"] = "generated"
    _write(staged / "manifest.json", manifest)
    data_dir = tmp_path / "data"
    first = Registry(data_dir=data_dir)
    ref = first.register_generated("art_style", staged)

    restarted = Registry(data_dir=data_dir)
    restarted.load()
    resolved = restarted.package_dir("art_style", ref)
    assert file_list_revision(resolved) == ref.revision
    generated = [
        item for item in restarted.list("art_style") if item.origin == "generated"
    ]
    assert [item.id for item in generated] == ["pixel_generated"]


def test_symlinked_generated_package_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "pixel"
    shutil.copytree(PLUGINS / "art_styles" / "pixel", outside)
    manifest = _read(outside / "manifest.json")
    manifest["origin"] = "generated"
    _write(outside / "manifest.json", manifest)
    staged = tmp_path / "staged"
    staged.mkdir()
    package = staged / "pixel"
    try:
        os.symlink(outside, package)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this host")
    registry = Registry(data_dir=tmp_path / "data")
    with pytest.raises(RegistryError) as error:
        registry.register_generated("art_style", package)
    assert error.value.code == "path_escape"
    assert not (tmp_path / "data" / "s").exists()


def test_typing_entries_parse_by_their_keys() -> None:
    registry = Registry()
    registry.load()
    assert isinstance(registry.get("sfx", "typing_keys"), TypingSoundEntry)
    assert isinstance(registry.get("sfx", "typing_fast"), TypingSoundEntry)
    assert isinstance(registry.get("sfx", "pop"), SfxEntry)


def test_missing_typing_key_file_is_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "sfx", "typing_keys")
    (package / "key-02.wav").unlink()
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "missing_file"


def test_typing_key_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "sfx", "typing_keys")
    key = package / "key-02.wav"
    key.write_bytes(key.read_bytes() + b"\0")
    with pytest.raises(RegistryError) as error:
        _registry(tmp_path).load()
    assert error.value.code == "digest_mismatch"


def test_legacy_typing_sfx_pin_survives_a_restart(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "sfx", "pop").rename(tmp_path / "sfx" / "legacy_typing")
    manifest = _read(package / "manifest.json")
    manifest["id"] = "legacy_typing"
    manifest["kind"] = "typing"
    _write(package / "manifest.json", manifest)
    plugin_root = tmp_path
    data_dir = tmp_path / "data"
    first = Registry(
        plugin_root=plugin_root, catalog_root=tmp_path / "catalog", data_dir=data_dir
    )
    first.load()
    ref = first.pin("sfx", "legacy_typing")
    assert isinstance(first.get("sfx", ref.id, ref.revision), SfxEntry)

    (package / "extra.txt").write_text("changed", encoding="utf-8")
    restarted = Registry(
        plugin_root=plugin_root, catalog_root=tmp_path / "catalog", data_dir=data_dir
    )
    restarted.load()
    assert restarted.pin("sfx", "legacy_typing").revision != ref.revision
    archived = restarted.get("sfx", ref.id, ref.revision)
    assert isinstance(archived, SfxEntry)
    assert archived.kind.value == "typing"
    assert file_list_revision(restarted.package_dir("sfx", ref)) == ref.revision


def test_typing_entry_resolves_from_the_archive_after_restart(tmp_path: Path) -> None:
    package = _copy_package(tmp_path, "sfx", "typing_keys")
    data_dir = tmp_path / "data"
    first = Registry(
        plugin_root=tmp_path, catalog_root=tmp_path / "catalog", data_dir=data_dir
    )
    first.load()
    ref = first.pin("sfx", "typing_keys")
    (package / "extra.txt").write_text("changed", encoding="utf-8")
    restarted = Registry(
        plugin_root=tmp_path, catalog_root=tmp_path / "catalog", data_dir=data_dir
    )
    restarted.load()
    entry = restarted.get("sfx", ref.id, ref.revision)
    assert isinstance(entry, TypingSoundEntry)
    assert restarted.pin("sfx", "typing_keys").revision != ref.revision
    assert restarted.package_dir("sfx", ref).name == ref.revision[:16]
