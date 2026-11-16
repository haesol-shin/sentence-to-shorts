"""Child process of the Qwen3-TTS adapter: loads the model once and answers requests.

The adapter starts this file as a script in its own process group, so it imports
nothing from `app`. The protocol is one ASCII JSON object per line.

Requests on stdin carry `id`, `text`, `language`, `speaker`, `seed`, `speed` and
`out`. Replies on the protocol stream are `ready` after the load, then `done` or
`error` per request, and `bye` when the worker leaves after its idle time. A closed
stdin ends the worker at once, so a parent that died never leaves a model running.

The model loads from a local folder only: remote code is never trusted and the
hub is never asked for a file. Library output is moved to stderr so nothing but
the protocol uses stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import sys
import threading
from typing import Any


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
    # Nobody reads a reply any more. Leave even in the middle of a synthesis.
    os._exit(0)


def _load(model_dir: str, threads: int) -> Any:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch

    torch.set_num_threads(threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    from qwen_tts import Qwen3TTSModel

    model = Qwen3TTSModel.from_pretrained(
        model_dir,
        device_map="cpu",
        dtype=torch.float32,
        trust_remote_code=False,
        local_files_only=True,
    )
    # The first speed change compiles numeric kernels; do it while loading, where the
    # load timeout applies, so the first sentence keeps its own timeout.
    import numpy

    _stretch(numpy.zeros(8192, dtype=numpy.float32), 24000, 1.1)
    return model


def _stretch(wave: Any, sample_rate: int, speed: float) -> Any:
    if speed == 1.0:
        return wave
    import librosa

    return librosa.effects.time_stretch(wave, rate=speed)


def _synthesize(model: Any, request: dict[str, Any]) -> dict[str, Any]:
    import numpy
    import soundfile
    import torch

    speakers = {name.lower() for name in model.get_supported_speakers() or []}
    if str(request["speaker"]).lower() not in speakers:
        return {"type": "error", "code": "speaker_unsupported"}
    torch.manual_seed(int(request["seed"]))
    waves, sample_rate = model.generate_custom_voice(
        text=request["text"], language=request["language"], speaker=request["speaker"]
    )
    if not waves:
        return {"type": "error", "code": "no_waveform"}
    wave = numpy.asarray(waves[0], dtype=numpy.float32)
    if wave.ndim != 1:
        return {"type": "error", "code": "invalid_waveform"}
    wave = _stretch(wave, int(sample_rate), float(request["speed"]))
    if wave.size == 0 or not numpy.isfinite(wave).all():
        return {"type": "error", "code": "invalid_waveform"}
    part = request["out"] + ".part"
    soundfile.write(part, wave, int(sample_rate), format="WAV", subtype="PCM_16")
    os.replace(part, request["out"])
    return {"type": "done", "sample_rate": int(sample_rate)}


def serve(model_dir: str, threads: int, idle_s: float) -> int:
    proto = _reply_stream()
    requests: queue.Queue[dict[str, Any]] = queue.Queue()
    threading.Thread(target=_read_requests, args=(requests,), daemon=True).start()
    try:
        model = _load(model_dir, threads)
    except ImportError as error:
        _send(proto, {"type": "error", "code": "package_missing", "name": error.name})
        return 1
    except Exception as error:  # noqa: BLE001 - reported to the adapter as one code
        _send(proto, {"type": "error", "code": "load_failed", "name": type(error).__name__})
        return 1
    _send(proto, {"type": "ready"})
    while True:
        try:
            request = requests.get(timeout=idle_s)
        except queue.Empty:
            _send(proto, {"type": "bye"})
            return 0
        try:
            reply = _synthesize(model, request)
        except Exception as error:  # noqa: BLE001 - one request must not end the worker
            reply = {"type": "error", "code": "synth_failed", "name": type(error).__name__}
        reply["id"] = request["id"]
        _send(proto, reply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--idle-s", type=float, required=True)
    args = parser.parse_args(argv)
    if args.threads < 1 or not math.isfinite(args.idle_s) or args.idle_s <= 0:
        parser.error("--threads and --idle-s must be positive")
    return serve(args.model_dir, args.threads, args.idle_s)


if __name__ == "__main__":
    sys.exit(main())
