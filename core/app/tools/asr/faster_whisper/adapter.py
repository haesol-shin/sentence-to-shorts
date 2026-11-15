"""``TranscriberPort`` over faster-whisper, reading a prepared model folder only.

The model lives under ``MODEL_DIR/faster-whisper-small/<revision>/`` where the
runtime setup put it after checking its hashes. This adapter never downloads: an
absent folder, an incomplete one or a missing package is ``model_missing``. The
model loads on the first call and stays loaded, and the heavy queue runs one job
at a time, so one worker holds it. Cancel is checked between segments.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from app.ports import AppError, AppSettings, CancelToken, Segment

RUNTIME_ITEM = "faster-whisper-small"
MODEL_FILES = ("model.bin", "config.json", "tokenizer.json")
COMPUTE_TYPE = "int8"
BEAM_SIZE = 5
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")


def find_model(model_dir: Path) -> Path | None:
    """The newest prepared revision folder with every model file, or None."""
    base = model_dir / RUNTIME_ITEM
    try:
        candidates = sorted(path for path in base.iterdir() if path.is_dir())
    except OSError:
        return None
    for path in reversed(candidates):
        if all((path / name).is_file() for name in MODEL_FILES):
            return path
    return None


class FasterWhisperTranscriber:
    def __init__(self, model_dir: Path) -> None:
        self.model_dir = model_dir
        self._model: Any = None
        self._lock = threading.Lock()

    def _loaded(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            path = find_model(self.model_dir)
            if path is None:
                raise AppError("model_missing", detail={"model": RUNTIME_ITEM})
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise AppError(
                    "model_missing", detail={"model": RUNTIME_ITEM, "reason": "package"}
                ) from error
            try:
                self._model = WhisperModel(
                    str(path), device="cpu", compute_type=COMPUTE_TYPE, local_files_only=True
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise AppError(
                    "model_missing", detail={"model": RUNTIME_ITEM, "reason": "load"}
                ) from error
            return self._model

    def transcribe(
        self, wav: Path, language: str | None, *, cancel: CancelToken
    ) -> list[Segment]:
        if language is not None and not _LANGUAGE.fullmatch(language):
            raise ValueError("language must be a short lowercase code or None")
        cancel.raise_if_set()
        model = self._loaded()
        cancel.raise_if_set()
        try:
            produced, _info = model.transcribe(
                str(wav), language=language, beam_size=BEAM_SIZE, vad_filter=True
            )
            segments: list[Segment] = []
            for item in produced:
                cancel.raise_if_set()
                text = str(item.text).strip()
                if text:
                    segments.append(
                        Segment(
                            start_ms=round(float(item.start) * 1000),
                            end_ms=round(float(item.end) * 1000),
                            text=text,
                        )
                    )
        except (RuntimeError, ValueError, OSError) as error:
            raise AppError("media_failed", detail={"step": "transcribe"}) from error
        return segments


def create(settings: AppSettings) -> FasterWhisperTranscriber:
    return FasterWhisperTranscriber(settings.model_dir)
