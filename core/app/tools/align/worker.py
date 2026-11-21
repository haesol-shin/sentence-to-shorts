"""Child process of the aligner adapter: loads one language model and aligns lines.

The adapter starts this file with the second environment's interpreter, so it
imports nothing from `app`. The protocol is one ASCII JSON object per line.

Requests on stdin carry `id`, `wav`, `speech_text`, `language` and `speech_ms`.
Replies are `ready` after the imports, then `words` or `error` per request, and
`bye` when the worker leaves after its idle time. A closed stdin ends the worker
at once, so a parent that died never leaves a model running.

Only the model of the requested language stays in memory; a switch to the other
language releases it before the next load. Models load from the prepared local
directories only, with the hub offline. `NLTK_DATA` points at the prepared
`punkt_tab` data, so the sentence splitter never downloads a file. Library
output is moved to stderr so nothing but the protocol uses stdout.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import queue
import sys
import threading
import wave
from pathlib import Path
from typing import Any

SAMPLE_RATE = 16000
ENGLISH_MODEL = "WAV2VEC2_ASR_BASE_960H"
LANGUAGES = ("ko", "en")


class ModelLoadError(Exception):
    """The aligner package or a prepared model file is missing."""


def _reply_stream() -> Any:
    """The original stdout as the protocol stream; fd 1 is rebound to stderr."""
    stream = os.fdopen(os.dup(1), "w", encoding="ascii", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return stream


def _send(stream: Any, message: dict[str, Any]) -> None:
    stream.write(json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n")
    stream.flush()


def _read_requests(requests: queue.Queue[dict[str, Any]]) -> None:
    for line in sys.stdin:
        line = line.strip()
        if line:
            requests.put(json.loads(line))
    # Nobody reads a reply any more. Leave even in the middle of an alignment.
    os._exit(0)


def _number(value: Any, key: str) -> float | None:
    item = value.get(key) if isinstance(value, dict) else None
    if not isinstance(item, (int, float)) or not math.isfinite(float(item)):
        return None
    return float(item)


def _words(aligned: Any) -> list[dict[str, Any]]:
    """The aligned words with only the fields the mapping rules read."""
    segments = aligned.get("word_segments") if isinstance(aligned, dict) else None
    if not isinstance(segments, list):
        raise ValueError("aligned result has no word segments")
    return [
        {
            "word": str(word.get("word", "")) if isinstance(word, dict) else "",
            "start": _number(word, "start"),
            "end": _number(word, "end"),
            "score": _number(word, "score"),
        }
        for word in segments
    ]


def _read_wav(path: str) -> Any:
    """A mono 16 kHz float waveform from a complete PCM16 WAV file."""
    import numpy
    import torch
    import torchaudio

    with wave.open(path, "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.getnframes()
        data = handle.readframes(frames)
    if (channels, width) != (1, 2) or frames <= 0 or len(data) != frames * 2:
        raise ValueError("wav is not mono PCM16")
    samples = numpy.frombuffer(data, dtype="<i2").astype(numpy.float32) / 32768.0
    if rate != SAMPLE_RATE:
        waveform = torch.from_numpy(samples)
        samples = torchaudio.functional.resample(waveform, rate, SAMPLE_RATE).numpy()
    return samples


class Engine:
    """The loaded language model and the alignment call over prepared files."""

    def __init__(self, model_ko: str, model_en: str, model_en_file: str, nltk_data: str) -> None:
        import torch

        self._torch = torch
        self._model_ko = Path(model_ko)
        self._model_en = Path(model_en)
        self._model_en_file = model_en_file
        self._nltk_data = Path(nltk_data)
        self._language: str | None = None
        self._model: Any = None
        self._metadata: dict[str, Any] | None = None
        self._whisperx: Any = None
        self._check_data()

    def _check_data(self) -> None:
        if not self._model_ko.is_dir():
            raise ModelLoadError("the Korean align model directory is missing")
        splitter = self._nltk_data / "tokenizers" / "punkt_tab" / "english"
        if not splitter.is_dir():
            raise ModelLoadError("the punkt_tab data is missing")

    def prepare(self) -> None:
        """Import WhisperX once; a missing package is a model-load failure."""
        try:
            import whisperx
        except ImportError as error:
            raise ModelLoadError(f"whisperx is missing: {error.name}") from error
        self._whisperx = whisperx

    def configure_threads(self, threads: int) -> None:
        self._torch.set_num_threads(threads)
        try:
            self._torch.set_num_interop_threads(1)
        except RuntimeError:
            pass

    def close(self) -> None:
        self._release()

    def _release(self) -> None:
        model = self._model
        self._model = None
        self._metadata = None
        self._language = None
        if model is not None:
            del model
            gc.collect()

    def _load(self, language: str) -> None:
        if language == "ko":
            model, metadata = self._whisperx.load_align_model(
                language_code="ko",
                device="cpu",
                model_name=str(self._model_ko),
                model_cache_only=True,
            )
        elif language == "en":
            # Checked here, not at start: a Korean video needs no English model, and a
            # missing file would make the loader download one.
            if not (self._model_en / self._model_en_file).is_file():
                raise ModelLoadError("the English align model file is missing")
            model, metadata = self._whisperx.load_align_model(
                language_code="en",
                device="cpu",
                model_name=ENGLISH_MODEL,
                model_dir=str(self._model_en),
            )
        else:
            raise ValueError(f"unsupported language: {language}")
        self._model = model
        self._metadata = metadata
        self._language = language

    def _loaded(self, language: str) -> None:
        if self._language == language:
            return
        self._release()
        self._load(language)

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        language = str(request.get("language", ""))
        if language not in LANGUAGES:
            return {"type": "error", "code": "language"}
        try:
            self._loaded(language)
        except ModelLoadError:
            raise
        except Exception as error:  # noqa: BLE001 - reported as a missing model
            raise ModelLoadError(type(error).__name__) from error
        if not isinstance(request.get("speech_text"), str) or not request["speech_text"]:
            return {"type": "error", "code": "empty_text"}
        speech_ms = request.get("speech_ms")
        if not isinstance(speech_ms, int) or speech_ms <= 0:
            return {"type": "error", "code": "speech_ms"}
        audio = _read_wav(str(request.get("wav", "")))
        segment = [{"text": request["speech_text"], "start": 0.0, "end": speech_ms / 1000}]
        aligned = self._whisperx.align(segment, self._model, self._metadata, audio, "cpu")
        return {"type": "words", "words": _words(aligned)}


def serve(model_ko: str, model_en: str, model_en_file: str, nltk_data: str, threads: int,
          idle_s: float) -> int:
    os.environ["NLTK_DATA"] = nltk_data
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    proto = _reply_stream()
    requests: queue.Queue[dict[str, Any]] = queue.Queue()
    threading.Thread(target=_read_requests, args=(requests,), daemon=True).start()
    try:
        engine = Engine(model_ko, model_en, model_en_file, nltk_data)
        engine.configure_threads(threads)
        engine.prepare()
    except ModelLoadError as error:
        _send(proto, {"type": "error", "code": "package_missing", "reason": str(error)})
        return 1
    except Exception as error:  # noqa: BLE001 - reported to the adapter as one code
        _send(proto, {"type": "error", "code": "load_failed", "name": type(error).__name__})
        return 1
    _send(proto, {"type": "ready"})
    while True:
        try:
            request = requests.get(timeout=idle_s)
        except queue.Empty:
            engine.close()
            _send(proto, {"type": "bye"})
            return 0
        try:
            reply = engine.answer(request)
        except ModelLoadError as error:
            reply = {"type": "error", "code": "model_load", "reason": str(error)}
        except Exception as error:  # noqa: BLE001 - one request must not end the worker
            reply = {"type": "error", "code": "align_failed", "name": type(error).__name__}
        reply["id"] = request.get("id")
        _send(proto, reply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-ko", required=True)
    parser.add_argument("--model-en", required=True)
    parser.add_argument("--model-en-file", required=True)
    parser.add_argument("--nltk-data", required=True)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--idle-s", type=float, required=True)
    args = parser.parse_args(argv)
    if args.threads < 1 or not math.isfinite(args.idle_s) or args.idle_s <= 0:
        parser.error("--threads and --idle-s must be positive")
    return serve(
        args.model_ko,
        args.model_en,
        args.model_en_file,
        args.nltk_data,
        args.threads,
        args.idle_s,
    )


if __name__ == "__main__":
    sys.exit(main())
