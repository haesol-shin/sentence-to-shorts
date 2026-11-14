"""Qwen3-TTS CustomVoice engine shared by the 0.6B and 1.7B probe candidates.

The official Python package and its default sampling are used as published.
The model snapshot is downloaded and pinned by ``models.json`` before the run.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import soundfile as sf

LANGUAGE_NAMES = {"ko": "Korean", "en": "English"}
SPEAKERS = {"ko": "Sohee", "en": "Ryan"}


class QwenEngine:
    candidate = ""
    speakers = SPEAKERS
    notes: dict[str, Any] = {}

    def __init__(
        self,
        *,
        threads: int,
        candidate: str,
        model_id: str,
        revision: str,
        local_dir: str,
    ) -> None:
        self.threads = max(1, int(threads))
        self.candidate = candidate
        self.model_id = model_id
        self.revision = revision
        self.model_path = Path(os.environ.get("PROBE_MODELS_DIR", ".local/probe/models")) / local_dir
        self.model = None
        self.notes = {
            "backend": "qwen-tts",
            "model_id": model_id,
            "revision": revision,
            "device": "cpu",
            "dtype": "float32",
            "sampling": "package default",
            "text_normalizer": "package default",
            "speaker_note": "preset speaker per language",
        }

    def load(self) -> None:
        import torch

        torch.set_num_threads(self.threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        if not self.model_path.is_dir():
            raise FileNotFoundError(f"model snapshot missing: {self.model_path}")
        from qwen_tts import Qwen3TTSModel

        self.model = Qwen3TTSModel.from_pretrained(
            str(self.model_path),
            device_map="cpu",
            dtype=torch.float32,
        )

    def synthesize(self, text: str, language: str, wav_path: Path) -> dict[str, Any] | None:
        if self.model is None:
            raise RuntimeError("engine is not loaded")
        wavs, sample_rate = self.model.generate_custom_voice(
            text=text,
            language=LANGUAGE_NAMES[language],
            speaker=self.speakers[language],
        )
        if not wavs:
            raise RuntimeError("model returned no waveform")
        sf.write(str(wav_path), wavs[0], int(sample_rate), subtype="PCM_16")
        return {"sample_rate": int(sample_rate)}

    def close(self) -> None:
        self.model = None
