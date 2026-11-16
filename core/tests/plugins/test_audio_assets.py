"""Builtin BGM and sound effect packages: manifests, digests and license coverage."""

from __future__ import annotations

import hashlib
import re
import wave
from pathlib import Path

import pytest

from app.plugins.registry import Registry
from app.schemas.bgm_entry import BuiltinBgm, SfxEntry, TypingSoundEntry

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
SfxManifest = SfxEntry | TypingSoundEntry


def _manifest(registry: Registry, kind: str, item_id: str) -> BuiltinBgm | SfxManifest:
    manifest = registry.get(kind, item_id)
    assert isinstance(manifest, (BuiltinBgm, SfxEntry, TypingSoundEntry))
    return manifest


def _entries(registry: Registry, kind: str) -> list[BuiltinBgm | SfxManifest]:
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
def sfx_entries(registry: Registry) -> list[SfxManifest]:
    entries = _entries(registry, "sfx")
    return [entry for entry in entries if isinstance(entry, (SfxEntry, TypingSoundEntry))]


def _package(kind: str, manifest: BuiltinBgm | SfxManifest) -> Path:
    return PLUGINS / kind / manifest.id


def _audio_files(manifest: BuiltinBgm | SfxManifest) -> list[tuple[Path, str, int | None]]:
    package = _package("bgm" if isinstance(manifest, BuiltinBgm) else "sfx", manifest)
    if isinstance(manifest, TypingSoundEntry):
        return [
            (package / key.file, key.sha256, key.duration_ms)
            for key in manifest.keys
        ]
    return [(package / manifest.file, manifest.sha256, manifest.duration_ms)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _ogg_audio(path: Path) -> tuple[int, int, int]:
    """Return sample rate, channels and duration ms of an Ogg Vorbis file."""
    data = path.read_bytes()
    offset = 0
    last_granule = -1
    while offset < len(data):
        assert data[offset : offset + 4] == b"OggS", (path, offset)
        segments = data[offset + 26]
        table = data[offset + 27 : offset + 27 + segments]
        page_end = offset + 27 + segments + sum(table)
        if offset == 0:
            identification = data[27 + segments : 27 + segments + 30]
            assert identification[:7] == b"\x01vorbis", path
            channels = identification[11]
            sample_rate = int.from_bytes(identification[12:16], "little")
        granule = int.from_bytes(data[offset + 6 : offset + 14], "little")
        if granule != 2**64 - 1:
            last_granule = granule
        offset = page_end
    assert last_granule >= 0, path
    return sample_rate, channels, round(last_granule * 1000 / sample_rate)


def test_manifest_registry_validation_loads_the_audio_packages(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxManifest]
) -> None:
    assert bgm_entries, "no builtin bgm package is registered"
    assert sfx_entries, "no builtin sfx package is registered"
    for manifest in [*bgm_entries, *sfx_entries]:
        kind = "bgm" if isinstance(manifest, BuiltinBgm) else "sfx"
        package = _package(kind, manifest)
        assert (package / "manifest.json").is_file()
        assert package.name == manifest.id


def test_manifest_sha256_matches_the_audio_file(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxManifest]
) -> None:
    for manifest in [*bgm_entries, *sfx_entries]:
        for audio, sha256, _ in _audio_files(manifest):
            assert audio.is_file(), audio
            assert _sha256(audio) == sha256, audio


def test_audio_file_header_matches_the_manifest(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxManifest]
) -> None:
    for manifest in [*bgm_entries, *sfx_entries]:
        for audio, _, declared_ms in _audio_files(manifest):
            if audio.suffix == ".ogg":
                assert isinstance(manifest, BuiltinBgm), audio
                sample_rate, channels, duration_ms = _ogg_audio(audio)
                assert sample_rate == manifest.sample_rate, audio
                assert channels == manifest.channels, audio
                assert duration_ms == pytest.approx(manifest.duration_ms, abs=50), audio
                continue
            with wave.open(str(audio), "rb") as handle:
                assert handle.getsampwidth() == 2, audio
                assert handle.getframerate() == 44100, audio
                frames = handle.getnframes()
                channels = handle.getnchannels()
            assert declared_ms == pytest.approx(frames * 1000 / 44100, abs=2), audio
            if isinstance(manifest, BuiltinBgm):
                assert channels == manifest.channels, audio
            else:
                assert channels == 1, audio


def _source_original_ms(package: Path) -> int:
    """Duration of the downloaded original recorded in the package SOURCE.txt."""
    for line in (package / "SOURCE.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("Original: "):
            match = re.search(r"([0-9]+(?:\.[0-9]+)?) s$", line)
            assert match is not None, (package, line)
            return round(float(match.group(1)) * 1000)
    raise AssertionError(f"{package} has no Original line")


def test_bgm_full_length_is_stored_as_ogg_vorbis(bgm_entries: list[BuiltinBgm]) -> None:
    for entry in bgm_entries:
        extension = ".wav" if entry.id == "builtin_loop" else ".ogg"
        assert entry.file.endswith(extension), entry.id


def test_bgm_full_length_keeps_the_original_duration(
    bgm_entries: list[BuiltinBgm],
) -> None:
    for entry in bgm_entries:
        if entry.id == "builtin_loop":
            continue
        original_ms = _source_original_ms(_package("bgm", entry))
        assert entry.duration_ms == pytest.approx(original_ms, abs=100), entry.id


def test_bgm_full_length_is_longer_than_30_seconds(bgm_entries: list[BuiltinBgm]) -> None:
    # Only an original longer than 30 s can pass; curious_stage_select lasts 21.33 s.
    for entry in bgm_entries:
        if entry.id == "builtin_loop":
            continue
        if _source_original_ms(_package("bgm", entry)) <= 30_000:
            continue
        assert entry.duration_ms > 30_000, entry.id


def test_mood_coverage_has_a_verified_entry_per_mood(bgm_entries: list[BuiltinBgm]) -> None:
    for mood in MOODS:
        verified = [
            entry
            for entry in bgm_entries
            if entry.mood == mood and entry.review_status == "verified"
        ]
        assert verified, f"mood {mood} has no verified bgm"


def test_license_attribution_is_present_for_cc_by_entries(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxManifest]
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
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxManifest]
) -> None:
    for kind, entries in (("bgm", bgm_entries), ("sfx", sfx_entries)):
        for manifest in entries:
            license_file = _package(kind, manifest) / manifest.license.license_file
            assert license_file.is_file(), license_file
            text = license_file.read_text(encoding="utf-8")
            assert text.strip(), license_file
            if manifest.license.spdx.casefold().startswith("cc-"):
                assert "Creative Commons" in text, license_file


def test_sfx_coverage_has_an_entry_per_kind(sfx_entries: list[SfxManifest]) -> None:
    for kind in SFX_KINDS:
        if kind == "typing":
            assert [
                entry for entry in sfx_entries if isinstance(entry, TypingSoundEntry)
            ], kind
        else:
            assert [
                entry
                for entry in sfx_entries
                if isinstance(entry, SfxEntry) and entry.kind == kind
            ], kind


def test_license_source_excludes_restricted_libraries(
    bgm_entries: list[BuiltinBgm], sfx_entries: list[SfxManifest]
) -> None:
    for manifest in [*bgm_entries, *sfx_entries]:
        host = str(manifest.license.source_url).split("/")[2].casefold()
        assert not any(
            host == restricted or host.endswith(f".{restricted}")
            for restricted in RESTRICTED_HOSTS
        ), manifest.id


def test_sfx_source_stays_within_its_declared_pack(sfx_entries: list[SfxManifest]) -> None:
    for entry in sfx_entries:
        if entry.license.author == "Project authors":
            continue
        host = str(entry.license.source_url).split("/")[2].casefold()
        if isinstance(entry, TypingSoundEntry):
            assert host == "opengameart.org", (entry.id, host)
        else:
            assert host == "kenney.nl", (entry.id, host)


def test_typing_entries_carry_key_sets(sfx_entries: list[SfxManifest]) -> None:
    typing = {
        entry.id: entry
        for entry in sfx_entries
        if isinstance(entry, TypingSoundEntry)
    }
    assert set(typing) == {"typing_keys", "typing_fast"}
    for entry in typing.values():
        assert 1 <= len(entry.keys) <= 64
        assert all(20 <= key.duration_ms <= 1000 for key in entry.keys)
    assert {key.sha256 for key in typing["typing_keys"].keys}.isdisjoint(
        {key.sha256 for key in typing["typing_fast"].keys}
    )
