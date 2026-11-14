#!/usr/bin/env python3
"""Synthesize the comparison script with Qwen3-TTS 1.7B CustomVoice.

The shared harness in ``probes/tts/common/`` measures cold start, first WAV,
RTF and peak RSS. Engine failures are written to ``result.json``; this script
still exits 0 for them.
"""

from __future__ import annotations

import sys
from pathlib import Path

COMMON = Path(__file__).resolve().parents[1] / "common"
sys.path.insert(0, str(COMMON))

from harness import main  # noqa: E402
from qwen3_tts_engine import QwenEngine  # noqa: E402

CANDIDATE = "qwen3-tts-1.7b"
MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
REVISION = "0c0e3051f131929182e2c023b9537f8b1c68adfe"
LOCAL_DIR = "Qwen3-TTS-12Hz-1.7B-CustomVoice"
PACKAGES = (
    "qwen-tts",
    "torch",
    "torchaudio",
    "transformers",
    "accelerate",
    "soundfile",
    "numpy",
    "onnxruntime",
)


def factory(threads: int) -> QwenEngine:
    return QwenEngine(
        threads=threads,
        candidate=CANDIDATE,
        model_id=MODEL_ID,
        revision=REVISION,
        local_dir=LOCAL_DIR,
    )


if __name__ == "__main__":
    sys.exit(main(factory, PACKAGES))
