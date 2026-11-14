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
TTS_DIR = "MOSS-TTS-Nano-100M-ONNX"
CODEC_DIR = "MOSS-Audio-Tokenizer-Nano-ONNX"
VOICE = {"ko": "Ava", "en": "Ava"}
MAX_NEW_FRAMES = 1500
PACKAGES = ("onnxruntime", "numpy", "sentencepiece", "soundfile")


def _decode(runtime: OrtCpuRuntime, frames: list[list[int]]) -> np.ndarray:
    """Decode frames to a channel-major float array with the runtime fallback."""
    try:
        channels, length = runtime.decode_full_audio(frames)
        if length > 0 and channels:
            return np.stack([np.asarray(channel[:length]) for channel in channels], axis=1)
    except Exception:  # noqa: BLE001 - fall back to the streaming decode path
        pass
    runtime.codec_streaming_session.reset()
    merged: list[list[np.ndarray]] = [list() for _ in range(int(runtime.codec_meta["codec_config"]["channels"]))]
    try:
        for start in range(0, len(frames), 8):
            decoded = runtime.codec_streaming_session.run_frames(frames[start : start + 8])
            if decoded is None:
                continue
            audio, length = decoded
            if length <= 0:
                continue
            for index in range(audio.shape[1]):
                merged[index].append(np.asarray(audio[0, index, :length], dtype=np.float32))
    finally:
        runtime.codec_streaming_session.reset()
    channels = [np.concatenate(parts) if parts else np.zeros((0,), dtype=np.float32) for parts in merged]
    if not channels or channels[0].size == 0:
        raise RuntimeError("codec returned no audio")
    length = min(channel.shape[0] for channel in channels)
    return np.stack([channel[:length] for channel in channels], axis=1)


class MossEngine:
    candidate = CANDIDATE
    speakers = VOICE
    notes: dict[str, Any] = {}

    def __init__(self, threads: int) -> None:
        self.threads = max(1, int(threads))
        self.models_root = Path(os.environ.get("PROBE_MODELS_DIR", ".probe/models"))
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
        for language, voice in VOICE.items():
            self.codes[language] = self.runtime.resolve_prompt_audio_codes(
                voice=voice, prompt_audio_path=None
            )

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
        }

    def close(self) -> None:
        self.runtime = None
        self.tokenizer = None


def factory(threads: int) -> MossEngine:
    return MossEngine(threads)


if __name__ == "__main__":
    sys.exit(main(factory, PACKAGES))
