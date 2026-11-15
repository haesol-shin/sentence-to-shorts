"""Contract-fixture videos with synthetic timings and TTS tones for sound and assembly tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.plugins.registry import Registry
from app.schemas.artifact import Timing
from app.schemas.video import Video
from tests.fixtures.media import tone_wav

VALID = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "valid"


def load(name: str) -> dict[str, Any]:
    return json.loads((VALID / name).read_text(encoding="utf-8"))


class Token:
    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


@dataclass
class Ctx:
    job_dir: Path
    cancel: Token = field(default_factory=Token)


def video(registry: Registry, *, bgm: str | None = "builtin_loop", **audio: Any) -> Video:
    """The Korean fixture video with its BGM pinned to the loaded registry."""
    raw = load("video_ko_just_three.json")
    settings = raw["settings"]["audio"]
    settings["bgm"]["entry"] = registry.pin("bgm", bgm).model_dump() if bgm else None
    settings["bgm"].update(audio)
    for scene in raw["scenes"].values():
        for cue in (scene.get("visual") or {}).get("sfx", []):
            cue["sfx_id"] = registry.pin("sfx", cue["sfx_id"]["id"]).model_dump()
    return Video.model_validate(raw)


def timings(built: Video, *, speech_ms: int = 1000, tail_ms: int = 400) -> list[Timing]:
    tts = load("timing_sentence_fallback.json")["lines"][0]["tts"]
    voice = load("timing_sentence_fallback.json")["voice"]
    result = []
    for scene_id in built.scene_order:
        scene = built.scenes[scene_id]
        lines = []
        cursor = 0
        for index, line in enumerate(scene.lines):
            start = 0 if index == 0 else cursor + 200
            lines.append(
                {
                    "line_id": line.id,
                    "tts": tts,
                    "start_ms": start,
                    "end_ms": start + speech_ms,
                    "speech_ms": speech_ms,
                    "caption": {"mode_used": "sentence", "fallback_reason": None, "phrases": []},
                }
            )
            cursor = start + speech_ms
        result.append(
            Timing.model_validate(
                {
                    "schema_version": 1,
                    "scene_id": scene_id,
                    "voice": voice,
                    "duration_ms": cursor + tail_ms,
                    "lines": lines,
                }
            )
        )
    return result


def tts_tones(built: Video, folder: Path, *, speech_ms: int = 1000) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    return {
        line.id: tone_wav(folder / f"{line.id}.wav", duration_ms=speech_ms, frequency=330.0)
        for scene in built.scenes.values()
        for line in scene.lines
    }
