#!/usr/bin/env python3
"""Synthesize the comparison script with the torch-free MOSS-TTS-Nano ONNX path.

Only the built-in voice presets are used, so no reference audio encoder and no
PyTorch are needed. Text normalization from the upstream Python package is not
part of this path; the plain SentencePiece encode is measured and recorded.

The shared harness in ``probes/tts/common/`` measures cold start, first WAV,
RTF and peak RSS. Engine failures are written to ``result.json``; this script
still exits 0 for them.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

COMMON = Path(__file__).resolve().parents[1] / "common"
sys.path.insert(0, str(COMMON))
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))

from harness import main  # noqa: E402
from ort_cpu_runtime import OrtCpuRuntime  # noqa: E402

CANDIDATE = "moss-tts-nano-100m"
SPEC = json.loads((Path(__file__).resolve().with_name("models.json")).read_text(encoding="utf-8"))
TTS_MODEL = SPEC["models"][0]
CODEC_MODEL = SPEC["models"][1]
TTS_DIR = TTS_MODEL["local_dir"]
CODEC_DIR = CODEC_MODEL["local_dir"]
VOICE = {"ko": "Ava", "en": "Ava"}
MAX_NEW_FRAMES = 1500
PACKAGES = ("onnxruntime", "numpy", "sentencepiece", "soundfile")


def _decode(runtime: OrtCpuRuntime, frames: list[list[int]]) -> np.ndarray:
    """Decode frames with the full decoder; a failure is the candidate result."""
    try:
        channels, length = runtime.decode_full_audio(frames)
    except Exception as exc:  # noqa: BLE001 - recorded with the original cause
        raise RuntimeError(f"full codec decode failed: {exc}") from exc
    if length <= 0 or not channels:
        raise RuntimeError("full codec decode returned no audio")
    return np.stack([np.asarray(channel[:length]) for channel in channels], axis=1)


class MossEngine:
    candidate = CANDIDATE
    speakers = VOICE
    notes: dict[str, Any] = {}

    def __init__(self, threads: int) -> None:
        self.threads = max(1, int(threads))
        self.models_root = Path(os.environ.get("PROBE_MODELS_DIR", ".local/probe/models"))
        self.runtime: OrtCpuRuntime | None = None
        self.tokenizer = None
        self.codes: dict[str, list[list[int]]] = {}
        self.notes = {
            "backend": "onnxruntime",
            "model_dir": TTS_DIR,
            "codec_dir": CODEC_DIR,
            "sample_mode": "fixed",
            "do_sample": True,
            "max_new_frames": MAX_NEW_FRAMES,
            "text_normalizer": "none",
            "speaker_note": "no Korean preset ships; the same preset reads Korean",
            "voice_clone_reference": "built-in preset codes from the manifest",
        }

    def load(self) -> None:
        import sentencepiece as spm

        manifest = self.models_root / TTS_DIR / "browser_poc_manifest.json"
        if not manifest.is_file():
            raise FileNotFoundError(f"model snapshot missing: {manifest}")
        self.runtime = OrtCpuRuntime(
            model_dir=self.models_root,
            thread_count=self.threads,
            max_new_frames=MAX_NEW_FRAMES,
            do_sample=True,
            sample_mode="fixed",
        )
        self.tokenizer = spm.SentencePieceProcessor(
            model_file=str(self.models_root / TTS_DIR / "tokenizer.model")
        )
        voices = {
            str(item["voice"]): item for item in self.runtime.list_builtin_voices()
        }
        for language, voice in VOICE.items():
            if voice not in voices:
                raise ValueError(
                    f"built-in voice not found: {voice}; available: {sorted(voices)}"
                )
            codes = voices[voice]["prompt_audio_codes"]
            if not codes:
                raise ValueError(f"built-in voice has no prompt codes: {voice}")
            self.codes[language] = [[int(value) for value in row] for row in codes]

    def synthesize(self, text: str, language: str, wav_path: Path) -> dict[str, Any] | None:
        if self.runtime is None or self.tokenizer is None:
            raise RuntimeError("engine is not loaded")
        token_ids = [int(item) for item in self.tokenizer.encode(text, out_type=int)]
        rows = self.runtime.build_voice_clone_request_rows(self.codes[language], token_ids)
        frames = self.runtime.generate_audio_frames(rows)
        if not frames:
            raise RuntimeError("model generated no frames")
        audio = _decode(self.runtime, frames)
        mono = audio.mean(axis=1)
        sample_rate = int(self.runtime.codec_meta["codec_config"]["sample_rate"])
        sf.write(str(wav_path), mono, sample_rate, subtype="PCM_16")
        return {
            "sample_rate": sample_rate,
            "channels": int(audio.shape[1]),
            "frames": len(frames),
            "truncated": len(frames) >= MAX_NEW_FRAMES,
            "text_tokens": len(token_ids),
            "decode_path": "full",
        }

    def close(self) -> None:
        self.runtime = None
        self.tokenizer = None


def factory(threads: int) -> MossEngine:
    return MossEngine(threads)


if __name__ == "__main__":
    sys.exit(main(factory, PACKAGES))
