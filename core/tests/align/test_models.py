"""Real synthesis and alignment with the prepared models: `pytest -m models`.

Needs `scripts/dev_setup.py --models` under APP_MODEL_DIR and the second
environment at APP_ALIGN_PYTHON (or `core/align_runtime/.venv`). The lines are
the three contract cases: K4 keeps its phrase timing through a number spelling,
E2 through a currency spelling, and K5 (code names) returns either phrase timing
or a sentence fallback, whichever the synthesis engine's word scores allow. The
low-score fallback itself is covered without models in test_mapping.py and
test_adapter.py.

The Qwen engine synthesizes each line once, then closes before the aligner runs,
so the two torch environments are never loaded at the same time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.jobs import CancelFlag
from app.ports import AppError
from app.schemas.voice_manifest import VoiceManifest
from app.settings import Settings
from app.tools.align.adapter import create as create_aligner
from app.tools.tts.qwen3_tts_0_6b.adapter import create as create_tts

pytestmark = [pytest.mark.models, pytest.mark.timeout(1800)]

FALLBACK_CODES = (
    "align_failed",
    "align_low_confidence",
    "align_missing_words",
    "align_unavailable",
)
REPO = Path(__file__).resolve().parents[3]
LINES = (
    (
        "K4",
        "ko",
        "가격은 12,500원이고, 성공률은 97.3퍼센트입니다.",
        "가격은 만 이천오백 원이고, 성공률은 구십칠 점 삼 퍼센트입니다.",
        "sohee_ko",
    ),
    (
        "E2",
        "en",
        "The price is $12.50.",
        "The price is twelve dollars and fifty cents.",
        "ryan_en",
    ),
    (
        "K5",
        "ko",
        "CPU와 GPU의 차이를 알고 있나요? Python API로 WAV 파일을 저장해 보세요.",
        "씨 피 유와 지 피 유의 차이를 알고 있나요? "
        "파이썬 에이 피 아이로 더블유 에이 브이 파일을 저장해 보세요.",
        "sohee_ko",
    ),
)


def _align_python() -> Path | None:
    configured = os.environ.get("APP_ALIGN_PYTHON")
    if configured:
        return Path(configured)
    name = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    candidate = REPO / "core" / "align_runtime" / ".venv" / name
    return candidate if candidate.is_file() else None


def _voice(name: str) -> VoiceManifest:
    path = REPO / "core" / "app" / "plugins" / "voices" / name / "manifest.json"
    return VoiceManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    python = _align_python()
    if python is None or not python.is_file():
        pytest.skip("set APP_ALIGN_PYTHON to the second environment's interpreter")
    model_dir = Path(os.environ.get("APP_MODEL_DIR") or REPO / ".local" / "models")
    probe = subprocess.run(
        [str(python), "-c", "import whisperx"],
        capture_output=True,
        check=False,
    )
    if probe.returncode:
        pytest.skip("the second environment does not import whisperx")
    data = tmp_path_factory.mktemp("align-models")
    wav_dir = tmp_path_factory.mktemp("align-wav")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("APP_PROFILE", "dev")
        patch.setenv("APP_DEPLOYMENT", "local")
        patch.setenv("APP_MODEL_DIR", str(model_dir))
        patch.setenv("APP_DATA_DIR", str(data / "data"))
        patch.setenv("APP_CACHE_DIR", str(data / "cache"))
        patch.setenv("APP_RUNTIME_DIR", str(data / "rt"))
        patch.setenv("APP_ALIGN_PYTHON", str(python))
        patch.setenv("APP_ALIGN_THREADS", "4")
        settings = Settings()
        tts = create_tts(settings)
        try:
            missing = tts.ready()
            if missing:
                pytest.skip(f"run scripts/dev_setup.py --models first: {missing}")
            wavs = {}
            try:
                for name, language, _, speech, voice in LINES:
                    wavs[name] = tts.synthesize(
                        speech,
                        language,
                        _voice(voice),
                        out_dir=wav_dir,
                        cancel=CancelFlag(),
                    )
            except AppError as error:
                if error.code == "tts_timeout":
                    pytest.skip("the host cannot synthesize within the TTS sentence timeout")
                raise
        finally:
            tts.close()
        aligner = create_aligner(settings)
        try:
            missing = aligner.missing()
            if missing:
                pytest.skip(f"run scripts/dev_setup.py --models first: {missing}")
            output = {}
            for name, language, display, speech, _ in LINES:
                output[name] = {
                    "result": aligner.align(
                        wavs[name].wav_path, speech, display, language, cancel=CancelFlag()
                    ),
                    "display": display,
                    "duration_ms": wavs[name].duration_ms,
                }
        finally:
            aligner.close()
    return output


def test_15_models_k4_number_keeps_phrase_timing(results) -> None:
    result = results["K4"]["result"]
    assert result.failure is None
    assert [(span.start_char, span.end_char) for span in result.phrases or []] == [
        (0, 14),
        (15, 31),
    ]


def test_15_models_e2_currency_keeps_phrase_timing(results) -> None:
    result = results["E2"]["result"]
    display = results["E2"]["display"]
    assert result.failure is None
    assert [(span.start_char, span.end_char) for span in result.phrases or []] == [
        (0, len(display))
    ]


def test_15_models_k5_code_names_keep_phrases_or_fall_back(results) -> None:
    result = results["K5"]["result"]
    display = results["K5"]["display"]
    if result.phrases is None:
        assert result.failure in FALLBACK_CODES
        return
    assert result.failure is None
    spans = result.phrases
    assert spans
    assert spans[0].start_char >= 0
    assert spans[-1].end_char <= len(display)
    for span in spans:
        assert span.start_char < span.end_char
        assert 0 <= span.start_ms < span.end_ms <= results["K5"]["duration_ms"]
    for before, after in zip(spans, spans[1:]):
        assert before.end_char <= after.start_char
        assert before.end_ms <= after.start_ms
