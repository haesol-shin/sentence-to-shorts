"""Builtin BGM and sound effect packages: manifests, digests and license coverage."""

from __future__ import annotations

import hashlib
import wave
from pathlib import Path

import pytest

from app.plugins.registry import Registry
from app.schemas.bgm_entry import BuiltinBgm, SfxEntry

PLUGINS = Path(__file__).resolve().parents[2] / "app" / "plugins"
MOODS = ("curious", "playful", "tense", "energetic", "calm", "reflective")
SFX_KINDS = ("whoosh", "pop", "ding", "click", "typing", "impact", "riser")
RESTRICTED_HOSTS = (
    "pixabay.com",
    "uppbeat.io",
    "mixkit.co",
    "youtube.com",
    "freepd.com",
)
ATTRIBUTION_SPDX = ("cc-by", "cc-by-sa")


def _manifest(registry: Registry, kind: str, item_id: str) -> BuiltinBgm | SfxEntry:
    manifest = registry.get(kind, item_id)
    assert isinstance(manifest, (BuiltinBgm, SfxEntry))
    return manifest


def _entries(registry: Registry, kind: str) -> list[BuiltinBgm | SfxEntry]:
    return [_manifest(registry, kind, item.id) for item in registry.list(kind)]


@pytest.fixture(scope="module")
def registry() -> Registry:
    registry = Registry()
    registry.load()
    return registry


@pytest.fixture(scope="module")
def bgm_entries(registry: Registry) -> list[BuiltinBgm]:
    entries = _entries(registry, "bgm")
    return [entry for entry in entries if isinstance(entry, BuiltinBgm)]


@pytest.fixture(scope="module")
def sfx_entries(registry: Registry) -> list[SfxEntry]:
    entries = _entries(registry, "sfx")
    return [entry for entry in entries if isinstance(entry, SfxEntry)]


def _package(kind: str, manifest: BuiltinBgm | SfxEntry) -> Path:
    return PLUGINS / kind / manifest.id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_manifest_registry_validation_loads_the_audio_packages(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxEntry]
) -> None:
    assert bgm_entries, "no builtin bgm package is registered"
    assert sfx_entries, "no builtin sfx package is registered"
    for manifest in [*bgm_entries, *sfx_entries]:
        kind = "bgm" if isinstance(manifest, BuiltinBgm) else "sfx"
        package = _package(kind, manifest)
        assert (package / "manifest.json").is_file()
        assert package.name == manifest.id


def test_manifest_sha256_matches_the_audio_file(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxEntry]
) -> None:
    for kind, entries in (("bgm", bgm_entries), ("sfx", sfx_entries)):
        for manifest in entries:
            audio = _package(kind, manifest) / manifest.file
            assert audio.is_file(), audio
            assert _sha256(audio) == manifest.sha256, audio


def test_audio_file_header_matches_the_manifest(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxEntry]
) -> None:
    for kind, entries in (("bgm", bgm_entries), ("sfx", sfx_entries)):
        for manifest in entries:
            audio = _package(kind, manifest) / manifest.file
            with wave.open(str(audio), "rb") as handle:
                assert handle.getsampwidth() == 2, audio
                assert handle.getframerate() == 44100, audio
                frames = handle.getnframes()
                channels = handle.getnchannels()
            assert manifest.duration_ms == pytest.approx(frames * 1000 / 44100, abs=2), audio
            if isinstance(manifest, BuiltinBgm):
                assert channels == manifest.channels, audio


def test_mood_coverage_has_a_verified_entry_per_mood(bgm_entries: list[BuiltinBgm]) -> None:
    for mood in MOODS:
        verified = [
            entry
            for entry in bgm_entries
            if entry.mood == mood and entry.review_status == "verified"
        ]
        assert verified, f"mood {mood} has no verified bgm"


def test_license_attribution_is_present_for_cc_by_entries(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxEntry]
) -> None:
    for manifest in [*bgm_entries, *sfx_entries]:
        spdx = manifest.license.spdx.casefold()
        if not spdx.startswith(ATTRIBUTION_SPDX):
            continue
        attribution = manifest.license.attribution
        assert attribution is not None, manifest.id
        assert attribution.ko.strip(), manifest.id
        assert attribution.en.strip(), manifest.id


def test_license_file_exists_and_names_the_license(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxEntry]
) -> None:
    for kind, entries in (("bgm", bgm_entries), ("sfx", sfx_entries)):
        for manifest in entries:
            license_file = _package(kind, manifest) / manifest.license.license_file
            assert license_file.is_file(), license_file
            text = license_file.read_text(encoding="utf-8")
            assert text.strip(), license_file
            if manifest.license.spdx.casefold().startswith("cc-"):
                assert "Creative Commons" in text, license_file


def test_sfx_coverage_has_an_entry_per_kind(sfx_entries: list[SfxEntry]) -> None:
    for kind in SFX_KINDS:
        assert [entry for entry in sfx_entries if entry.kind == kind], kind


def test_license_source_excludes_restricted_libraries(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxEntry]
) -> None:
    for manifest in [*bgm_entries, *sfx_entries]:
        host = str(manifest.license.source_url).split("/")[2].casefold()
        assert not any(
            host == restricted or host.endswith(f".{restricted}")
            for restricted in RESTRICTED_HOSTS
        ), manifest.id


def test_sfx_source_stays_within_the_kenney_pack(sfx_entries: list[SfxEntry]) -> None:
    for entry in sfx_entries:
        if entry.license.author == "Project authors":
            continue
        host = str(entry.license.source_url).split("/")[2].casefold()
        assert host == "kenney.nl", (entry.id, host)
