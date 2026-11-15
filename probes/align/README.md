# 정렬 probe

측정 결과와 판정은 [RESULT.md](RESULT.md)에 있다.

알려진 대본을 WhisperX 3.8.6으로 forced alignment해 CPU에서의 정확도와 시간, 메모리를 잰다. 같은 환경에 TTS 후보의 요구 사항을 넣을 수 있는지도 해석 단계에서 확인한다. 전사는 하지 않는다. 이 디렉터리는 probe 코드이며 제품 의존성과 lockfile에 들어가지 않는다.

## 구성

| 경로 | 역할 |
| --- | --- |
| `texts.json` | 고정 시험 대본 12줄. 한국어 8줄, 영어 4줄. 숫자와 코드명이 있는 줄은 화면 글과 말할 글을 따로 둔다 |
| `mapping.py` | 화면 글의 구절 범위와 말할 글 단어 시간을 잇고 판정을 내리는 순수 함수 |
| `align_probe.py` | WAV마다 정렬을 실행하고 `results.json`을 쓴다 |
| `install_matrix.py` | 후보 요구 사항과 WhisperX를 한 환경으로 해석해 결과를 적는다 |
| `measure_env.py` | 설치 환경과 모델 cache의 bytes, 설치된 버전을 잰다 |
| `tests/` | 구절 분할, 숫자·코드명 대응, 실패 판정 시험. model과 audio 없이 돈다 |
| `RESULT.md`, `results/` | 측정 표와 이 호스트에서 낸 결과 JSON |

## 실행

정렬 환경은 Python 3.11 가상 환경에 `whisperx==3.8.6`을 설치해 만든다. CPU만 쓴다.

```sh
python -m venv .local/probe/align-venv
.local/probe/align-venv/bin/python -m pip install whisperx==3.8.6
```

시험 음성은 이 저장소에 넣지 않는다. ONNX TTS probe로 `texts.json`의 말할 글을 합성한다. 같은 파일을 그대로 읽으므로 별도 변환이 필요 없다.

```sh
PROBE_MODELS_DIR=.local/probe/models \
  python probes/tts/common/fetch_models.py \
  --spec probes/tts/moss-tts-nano-100m/models.json --root .local/probe/models
PROBE_MODELS_DIR=.local/probe/models \
  .local/probe/tts-venv/bin/python probes/tts/moss-tts-nano-100m/synth.py \
  --texts probes/align/texts.json --out .local/probe/audio --threads 4 --repeats 1
```

정렬은 WAV마다 한 번씩 돌리고, `--repeats 2`를 주면 같은 줄을 두 번 정렬해 단어 시간이 같은지도 적는다.

```sh
NLTK_DATA=.local/probe/nltk HF_HOME=.local/probe/hf TORCH_HOME=.local/probe/torch \
  .local/probe/align-venv/bin/python probes/align/align_probe.py \
  --audio-dir .local/probe/audio/wav --out .local/probe/align-result.json --repeats 2
```

`results.json`의 `gate`는 모든 줄이 실패 없이 매핑되면 `pass`다. 줄마다 `verdict`, `reasons`, `phrases`, `words`가 있고, 실패한 줄은 구절 범위 대신 실패 이유만 남는다.

후보 넷의 요구 사항을 WhisperX와 함께 해석하려면 `uv`가 필요하다. 설치하지 않고 의존성만 푼다.

```sh
python probes/align/install_matrix.py \
  --platform x86_64-manylinux_2_28 --platform aarch64-manylinux_2_28 \
  --out .local/probe/install-matrix.json
```

설치 크기와 모델 bytes는 측정 환경 안에서 잰다.

```sh
.local/probe/align-venv/bin/python probes/align/measure_env.py \
  --env .local/probe/align-venv --cache .local/probe/hf --cache .local/probe/torch \
  --out .local/probe/env.json
```

## 판정 규칙

- 구절은 문장부호와 쉼표 뒤에서 나눈다. 화면 글의 구절마다 말할 글 단어의 시작과 끝을 모아 `start_char`, `end_char`, `start_ms`, `end_ms`를 만든다.
- 화면 글 단어와 말할 글 단어는 정규화한 뒤 순서대로 맞춘다. 숫자, 통화, 대문자 코드명, 한글과 로마자 사이의 치환만 다른 단어로 인정한다. 그 밖의 치환과 화면 쪽에만 있는 단어는 `align_missing_words`다.
- 말할 글 단어 수와 정렬기가 돌려준 단어 수가 다르거나, 구절 수가 다르거나, 시간이 없는 단어가 있으면 `align_missing_words`다.
- 단어 점수가 `LOW_CONFIDENCE_SCORE`보다 낮으면 `align_low_confidence`다. 점수는 결과에 모두 남기므로 문턱을 바꿔 다시 판정할 수 있다.
- 단어 시간이 순서를 어기면 `align_failed`다. 정렬기 예외와 model load 실패도 `align_failed` 또는 `align_unavailable`로 남는다.
- 실패한 줄은 구절 범위를 만들지 않는다. 제품에서는 그 줄이 문장형 자막이 된다.

## CI

[workflow](../../.github/workflows/probe-align.yml)는 pull request와 수동 실행에서 돈다. ubuntu에서는 정렬 환경 설치, 후보 해석, TTS 합성, 정렬, 크기 측정을 한 번에 돌리고 결과 JSON을 artifact로 올린다. windows-latest는 수동 실행에서 입력을 켤 때만 붙는다.

pull request 실행은 `x86_64-manylinux_2_28`만 본다. 개발 기기는 aarch64라서 x64 수치는 CI에서만 나온다.

## 버전

정렬 환경은 `whisperx==3.8.6`과 그 전이 의존성을 PyPI에서 그대로 설치한다. 정렬 model은 언어별 기본값을 쓴다. 한국어는 `kresnik/wav2vec2-large-xlsr-korean`, 영어는 torchaudio의 `WAV2VEC2_ASR_BASE_960H`다. 합성 음성은 ONNX TTS 후보 하나로 만들며, 그 model revision은 `probes/tts/moss-tts-nano-100m/models.json`이 원본이다.
