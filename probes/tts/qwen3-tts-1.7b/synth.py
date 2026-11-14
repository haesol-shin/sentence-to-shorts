#!/usr/bin/env python3
"""Synthesize the comparison script with Qwen3-TTS 1.7B CustomVoice.

The shared harness in ``probes/tts/common/`` measures cold start, first WAV,
RTF and peak RSS. Engine failures are written to ``result.json``; this script
still exits 0 for them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

COMMON = Path(__file__).resolve().parents[1] / "common"
sys.path.insert(0, str(COMMON))

from harness import main  # noqa: E402
from qwen3_tts_engine import QwenEngine  # noqa: E402

CANDIDATE = "qwen3-tts-1.7b"
MODEL = json.loads(
    (Path(__file__).resolve().with_name("models.json")).read_text(encoding="utf-8")
)["models"][0]
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
        model_id=MODEL["repo_id"],
        revision=MODEL["revision"],
        local_dir=MODEL["local_dir"],
    )


if __name__ == "__main__":
    sys.exit(main(factory, PACKAGES))
