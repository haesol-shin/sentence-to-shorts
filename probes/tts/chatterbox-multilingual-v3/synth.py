#!/usr/bin/env python3
"""Synthesize the comparison script with Chatterbox Multilingual V3 ONNX (q4).

The graph contract follows the published ONNX export card and the reference
runtime for the same graph family: tokenizer.json, speech encoder on the
bundled reference, KV-cached greedy decode of the q4 language model with
repetition penalty 1.2, then the conditional decoder. V3 drops the audio of the
final speech token before STOP.

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
import onnxruntime as ort
import soundfile as sf
from tokenizers import Tokenizer

COMMON = Path(__file__).resolve().parents[1] / "common"
sys.path.insert(0, str(COMMON))

from harness import main  # noqa: E402

CANDIDATE = "chatterbox-multilingual-v3"
LOCAL_DIR = "chatterbox-multilingual-v3-ONNX"
SAMPLE_RATE = 24000
START_SPEECH_TOKEN = 6561
STOP_SPEECH_TOKEN = 6562
NUM_LAYERS = 30
NUM_KV_HEADS = 16
HEAD_DIM = 64
SAMPLES_PER_TOKEN = 960
EXAGGERATION = 0.5
REPETITION_PENALTY = 1.2
MAX_NEW_TOKENS = 1024
REFERENCE_NAME = "default_voice"
SPEAKERS = {"ko": REFERENCE_NAME, "en": REFERENCE_NAME}
PACKAGES = ("onnxruntime", "numpy", "tokenizers", "soundfile")


def _session(path: Path, threads: int) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    return ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def _apply_repetition_penalty(
    token_ids: np.ndarray, scores: np.ndarray, penalty: float
) -> np.ndarray:
    score = np.take_along_axis(scores, token_ids, axis=1)
    score = np.where(score < 0, score * penalty, score / penalty)
    processed = scores.copy()
    np.put_along_axis(processed, token_ids, score, axis=1)
    return processed


class ChatterboxEngine:
    candidate = CANDIDATE
    speakers = SPEAKERS
    notes: dict[str, Any] = {}

    def __init__(self, threads: int) -> None:
        self.threads = max(1, int(threads))
        self.model_dir = (
            Path(os.environ.get("PROBE_MODELS_DIR", ".probe/models")) / LOCAL_DIR
        )
        self.sessions: dict[str, ort.InferenceSession] = {}
        self.tokenizer: Tokenizer | None = None
        self.reference: np.ndarray | None = None
        self.notes = {
            "backend": "onnxruntime",
            "language_model": "language_model_q4.onnx",
            "exaggeration": EXAGGERATION,
            "sampling": f"greedy, repetition penalty {REPETITION_PENALTY}",
            "max_new_tokens": MAX_NEW_TOKENS,
            "text_preprocessing": "tokenizer.json NFKD full-case, language prefix",
            "reference": f"{REFERENCE_NAME}.wav",
            "trim": "final speech token audio dropped (V3 rule)",
            "text_normalizer": "none",
            "speaker_note": "single bundled reference; Korean uses the same reference",
        }

    def load(self) -> None:
        onnx_dir = self.model_dir / "onnx"
        tokenizer_path = self.model_dir / "tokenizer.json"
        if not tokenizer_path.is_file():
            raise FileNotFoundError(f"model snapshot missing: {tokenizer_path}")
        self.sessions = {
            "speech_encoder": _session(onnx_dir / "speech_encoder.onnx", self.threads),
            "embed_tokens": _session(onnx_dir / "embed_tokens.onnx", self.threads),
            "language_model": _session(onnx_dir / "language_model_q4.onnx", self.threads),
            "conditional_decoder": _session(
                onnx_dir / "conditional_decoder.onnx", self.threads
            ),
        }
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        audio, sample_rate = sf.read(
            str(self.model_dir / f"{REFERENCE_NAME}.wav"), dtype="float32", always_2d=True
        )
        if audio.shape[1] > 1:
            audio = audio.mean(axis=1)
        else:
            audio = audio[:, 0]
        if sample_rate != SAMPLE_RATE:
            duration = audio.shape[0] / float(sample_rate)
            target = np.linspace(0.0, duration, int(duration * SAMPLE_RATE), endpoint=False)
            audio = np.interp(target, np.arange(audio.shape[0]) / sample_rate, audio).astype(
                np.float32
            )
        self.reference = audio[np.newaxis, :]

    def _past_names(self) -> dict[str, str]:
        names = {}
        for layer in range(NUM_LAYERS):
            for kind in ("key", "value"):
                names[f"past_key_values.{layer}.{kind}"] = f"present.{layer}.{kind}"
        return names

    def _empty_past(self, batch: int) -> dict[str, np.ndarray]:
        return {
            f"past_key_values.{layer}.{kind}": np.zeros(
                [batch, NUM_KV_HEADS, 0, HEAD_DIM], dtype=np.float32
            )
            for layer in range(NUM_LAYERS)
            for kind in ("key", "value")
        }

    def synthesize(self, text: str, language: str, wav_path: Path) -> dict[str, Any] | None:
        if self.tokenizer is None or self.reference is None:
            raise RuntimeError("engine is not loaded")
        encoded = self.tokenizer.encode(f"[{language}]{text}").ids
        input_ids = np.asarray([encoded], dtype=np.int64)
        steps = np.arange(input_ids.shape[1])[np.newaxis, :] - 1
        position_ids = np.where(input_ids >= START_SPEECH_TOKEN, 0, steps).astype(np.int64)
        embed_feeds = {
            "input_ids": input_ids,
            "position_ids": position_ids,
            "exaggeration": np.asarray([EXAGGERATION], dtype=np.float32),
        }
        generated = np.asarray([[START_SPEECH_TOKEN]], dtype=np.int64)
        past = self._empty_past(input_ids.shape[0])
        past_names = self._past_names()
        attention_mask = None
        prompt_tokens = None
        speaker_embeddings = None
        speaker_features = None

        for index in range(MAX_NEW_TOKENS):
            inputs_embeds = self.sessions["embed_tokens"].run(None, embed_feeds)[0]
            if index == 0:
                encoder = self.sessions["speech_encoder"].run(
                    None, {"audio_values": self.reference}
                )
                names = [
                    output.name for output in self.sessions["speech_encoder"].get_outputs()
                ]
                outputs = dict(zip(names, encoder, strict=True))
                inputs_embeds = np.concatenate(
                    (outputs["audio_features"], inputs_embeds), axis=1
                )
                prompt_tokens = outputs["audio_tokens"].astype(np.int64)
                speaker_embeddings = outputs["speaker_embeddings"]
                speaker_features = outputs["speaker_features"]
                attention_mask = np.ones(inputs_embeds.shape[:2], dtype=np.int64)
            feeds = {
                "inputs_embeds": inputs_embeds,
                "attention_mask": attention_mask,
                **past,
            }
            results = self.sessions["language_model"].run(None, feeds)
            names = [
                output.name for output in self.sessions["language_model"].get_outputs()
            ]
            named = dict(zip(names, results, strict=True))
            logits = named["logits"][:, -1, :]
            logits = _apply_repetition_penalty(generated, logits, REPETITION_PENALTY)
            next_token = np.argmax(logits, axis=-1, keepdims=True).astype(np.int64)
            generated = np.concatenate((generated, next_token), axis=-1)
            if bool((next_token == STOP_SPEECH_TOKEN).all()):
                break
            embed_feeds["input_ids"] = next_token
            embed_feeds["position_ids"] = np.full(
                (input_ids.shape[0], 1), index + 1, dtype=np.int64
            )
            attention_mask = np.concatenate(
                [attention_mask, np.ones((attention_mask.shape[0], 1), dtype=np.int64)],
                axis=1,
            )
            past = {
                key: named[past_names[key]] for key in past
            }
        else:
            raise RuntimeError(f"generation hit the {MAX_NEW_TOKENS} token limit")

        if prompt_tokens is None or speaker_embeddings is None or speaker_features is None:
            raise RuntimeError("speech encoder did not run")
        speech_tokens = np.concatenate([prompt_tokens, generated[:, 1:-1]], axis=1)
        waveform = self.sessions["conditional_decoder"].run(
            None,
            {
                "speech_tokens": speech_tokens,
                "speaker_embeddings": speaker_embeddings,
                "speaker_features": speaker_features,
            },
        )[0]
        waveform = np.asarray(waveform).reshape(-1)
        keep = max(0, (speech_tokens.shape[1] - 1) * SAMPLES_PER_TOKEN)
        if keep:
            waveform = waveform[:keep]
        if waveform.size == 0:
            raise RuntimeError("decoder returned no audio")
        sf.write(str(wav_path), waveform, SAMPLE_RATE, subtype="PCM_16")
        return {
            "sample_rate": SAMPLE_RATE,
            "speech_tokens": int(speech_tokens.shape[1]),
            "generated_tokens": int(generated.shape[1] - 1),
            "text_tokens": len(encoded),
        }

    def close(self) -> None:
        self.sessions = {}
        self.tokenizer = None
        self.reference = None


def factory(threads: int) -> ChatterboxEngine:
    return ChatterboxEngine(threads)


if __name__ == "__main__":
    sys.exit(main(factory, PACKAGES))
