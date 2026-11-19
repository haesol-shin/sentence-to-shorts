"""``TranscriberPort`` over faster-whisper, reading a prepared model folder only.

The model lives under ``MODEL_DIR/faster-whisper-small/<revision>/`` where the
runtime setup put it after checking its hashes. This adapter never downloads: an
absent folder, an incomplete one or a missing package is ``model_missing``. The
model loads on the first call and stays loaded, and the heavy queue runs one job
at a time, so one worker holds it. Cancel is checked between segments.

The device is picked once when the adapter is built. `auto` takes CUDA when
ctranslate2 reports a device, and a failed CUDA load steps down to the CPU once;
an explicit `cuda` that cannot load stays an error. The chosen device and the
reason go to the runtime status.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from app.ports import AppError, AppSettings, CancelToken, Segment
from app.tools.device import DeviceSelection

RUNTIME_ITEM = "faster-whisper-small"
MODEL_FILES = ("model.bin", "config.json", "tokenizer.json")
COMPUTE_TYPE = "int8"
BEAM_SIZE = 5
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")

logger = logging.getLogger(__name__)


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


def cuda_device_count() -> int:
    """CUDA devices ctranslate2 can use; faster-whisper runs on the same library.

    Device detection must not make the app fail to start when the inference
    package cannot be imported on this host. The transcription call still reports
    the package as `model_missing` when it is needed.
    """
    try:
        import ctranslate2
    except (ImportError, OSError):
        return 0
    return int(ctranslate2.get_cuda_device_count())


def cuda_compute_type_supported() -> bool:
    """Whether the configured compute type runs on CUDA device 0.

    A CUDA-capable ctranslate2 build can still refuse a quantized compute type on
    an older GPU. A typed `cuda` must hear that at startup, not on the first
    transcript, so this asks the backend before the model is opened.
    """
    import ctranslate2

    try:
        supported = ctranslate2.get_supported_compute_types("cuda", 0)
    except (RuntimeError, ValueError):
        return False
    return COMPUTE_TYPE in supported


def cuda_runtime_available() -> bool:
    """True when the cuBLAS library ctranslate2 loads for CUDA int8 is present.

    The compute-type query only reads GPU properties; the int8 primitive loads
    cuBLAS on its first call. A typed `cuda` must know that at startup, and `auto`
    must fall back before the first transcript.
    """
    import ctypes
    import os
    import sys

    candidates = ["libcublas.so.12"]
    if sys.platform == "win32":
        candidates = ["cublas64_12.dll"]
        cuda_path = os.environ.get("CUDA_PATH")
        if cuda_path:
            candidates.insert(0, os.path.join(cuda_path, "bin", "cublas64_12.dll"))
    for name in candidates:
        try:
            ctypes.CDLL(name)
        except OSError:
            continue
        return True
    return False


def cuda_problem() -> str | None:
    """None when the backend and its CUDA runtime can run int8, else why not."""
    if not cuda_compute_type_supported():
        return "ctranslate2 cannot run int8 on a CUDA device"
    if not cuda_runtime_available():
        return "ctranslate2 cannot load the CUDA runtime"
    return None


class FasterWhisperTranscriber:
    def __init__(
        self,
        model_dir: Path,
        *,
        selection: DeviceSelection | None = None,
    ) -> None:
        self.model_dir = model_dir
        self._selection = selection or DeviceSelection("cpu", "cpu", "configured")
        self._model: Any = None
        self._lock = threading.Lock()
        self._transcribed = False

    @property
    def device(self) -> str:
        """The device the model loads on, after a possible CPU step-down."""
        return self._selection.snapshot()[0]

    @property
    def device_reason(self) -> str:
        """Why that device was chosen: configured, detected, unavailable, load_failed."""
        return self._selection.snapshot()[1]

    def device_status(self) -> tuple[str, str]:
        """The device and reason from one state, for the runtime status."""
        return self._selection.snapshot()

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
                self._model = self._load(WhisperModel, path)
            except (OSError, RuntimeError, ValueError) as error:
                raise AppError(
                    "model_missing", detail={"model": RUNTIME_ITEM, "reason": "load"}
                ) from error
            return self._model

    def _load(self, model_class: Any, path: Path) -> Any:
        try:
            return model_class(
                str(path),
                device=self._selection.device,
                compute_type=COMPUTE_TYPE,
                local_files_only=True,
            )
        except (OSError, RuntimeError, ValueError) as error:
            if not self._selection.may_fall_back:
                raise
            logger.warning(
                "faster-whisper could not load on cuda (%s); retrying on cpu",
                type(error).__name__,
            )
            self._selection.step_down()
            return model_class(
                str(path), device="cpu", compute_type=COMPUTE_TYPE, local_files_only=True
            )

    def transcribe(
        self, wav: Path, language: str | None, *, cancel: CancelToken
    ) -> list[Segment]:
        if language is not None and not _LANGUAGE.fullmatch(language):
            raise ValueError("language must be a short lowercase code or None")
        cancel.raise_if_set()
        model = self._loaded()
        cancel.raise_if_set()
        try:
            segments = self._run(model, wav, language, cancel)
        except (RuntimeError, ValueError, OSError) as error:
            if not self._selection.may_fall_back or self._transcribed:
                raise AppError("media_failed", detail={"step": "transcribe"}) from error
            # A GPU runtime library can fail on the first real inference. Retry
            # that one inference on the CPU, as the auto policy allows.
            logger.warning(
                "faster-whisper cuda inference failed (%s); retrying on cpu",
                type(error).__name__,
            )
            self._selection.step_down()
            self._model = None
            try:
                segments = self._run(self._loaded(), wav, language, cancel)
            except (RuntimeError, ValueError, OSError) as retry_error:
                raise AppError("media_failed", detail={"step": "transcribe"}) from retry_error
        self._transcribed = True
        return segments

    def _run(
        self, model: Any, wav: Path, language: str | None, cancel: CancelToken
    ) -> list[Segment]:
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
        return segments


def create(settings: AppSettings) -> FasterWhisperTranscriber:
    requested = str(getattr(settings, "device", "auto"))
    selection = DeviceSelection.resolve(
        requested,
        detect=lambda: cuda_device_count() > 0,
        verify=cuda_problem,
        verify_auto=True,
        backend="ctranslate2",
    )
    return FasterWhisperTranscriber(settings.model_dir, selection=selection)
