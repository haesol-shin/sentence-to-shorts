"""The Korean and English voice manifests pass the registry and match the engine."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from app.plugins.registry import Registry
from app.schemas.voice_manifest import VoiceManifest
from app.tools.tts.qwen3_tts_0_6b.adapter import ENGINE_ID, MODEL_ITEM, SAMPLE_RATE

LOCK = Path(__file__).resolve().parents[2] / "config" / "runtime.lock.json"
VOICES = {"sohee_ko": ("ko", "Sohee"), "ryan_en": ("en", "Ryan")}


@pytest.fixture(scope="module")
def registry() -> Registry:
    loaded = Registry()
    loaded.load()
    return loaded


def manifest(registry: Registry, voice_id: str) -> VoiceManifest:
    found = registry.get("voice", voice_id)
    assert isinstance(found, VoiceManifest)
    return found


def test_9_catalog_lists_a_korean_and_an_english_voice(registry: Registry) -> None:
    listed = {item.id for item in registry.list("voice")}
    assert set(VOICES) <= listed
    for voice_id, (language, _) in VOICES.items():
        assert language in [value.value for value in manifest(registry, voice_id).languages]


@pytest.mark.parametrize("voice_id", VOICES)
def test_9_voice_names_the_selected_engine_and_its_pinned_model(
    registry: Registry, voice_id: str
) -> None:
    language, speaker = VOICES[voice_id]
    voice = manifest(registry, voice_id)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    pinned = next(item for item in lock["items"] if item["id"] == MODEL_ITEM)
    assert voice.engine_id == ENGINE_ID
    assert voice.cloning is False
    assert [value.value for value in voice.languages] == [language]
    assert voice.speaker == speaker
    assert voice.model is not None
    assert (voice.model.runtime_item, voice.model.revision) == (MODEL_ITEM, pinned["revision"])
    assert voice.model.repo == "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert (voice.output.sample_rate, voice.output.channels) == (SAMPLE_RATE, 1)
    assert voice.license.spdx == "Apache-2.0"
    assert voice.license.commercial_ok is True


@pytest.mark.parametrize("voice_id", VOICES)
def test_9_voice_sample_is_a_short_mono_wav_at_the_engine_rate(
    registry: Registry, voice_id: str
) -> None:
    voice = manifest(registry, voice_id)
    package = registry.package_dir("voice", registry.pin("voice", voice_id))
    with wave.open(str(package / voice.sample.file), "rb") as handle:
        assert (handle.getnchannels(), handle.getsampwidth()) == (1, 2)
        assert handle.getframerate() == SAMPLE_RATE
        seconds = handle.getnframes() / SAMPLE_RATE
    assert 1.0 <= seconds <= 8.0
    assert (package / voice.license.license_file).is_file()


