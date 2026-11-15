# 정렬과 동시 설치 결과

WhisperX 3.8.6으로 알려진 대본을 CPU에서 정렬하고, 화면 글의 구절 범위를 말할 글 단어 시간에 잇는 규칙을 시험함. TTS 후보의 요구 사항을 같은 환경에 넣을 수 있는지도 해석 단계에서 확인함. 결과 수치는 이 문서와 `results/`의 JSON에 있는 실측값만 적음.

## 측정 조건

- 호스트는 aarch64 Linux, 4 vCPU, 7 GiB RAM이고 CPU만 씀. Python 3.11.15, whisperx 3.8.6, torch 2.8.0, transformers 4.57.6임.
- 저장된 후보 WAV가 없어 같은 대본을 ONNX TTS 후보 `moss-tts-nano-100m`으로 합성해 입력으로 씀. 12줄 합계 81.76초, 48 kHz mono PCM16임.
- 합성 artifact는 `results/linux-aarch64-audio.json`, 정렬 artifact는 `results/linux-aarch64-align.json`임.
- 정렬은 `align_probe.py --repeats 2`로 두 번 돌려 단어 시간이 같은지 함께 적음. model은 언어마다 하나씩 차례로 load하고 다음 언어 전에 놓아 줌.
- 한국어 model은 `kresnik/wav2vec2-large-xlsr-korean`, 영어 model은 torchaudio의 `WAV2VEC2_ASR_BASE_960H`임.

## 정렬 결과

| 줄 | 언어 | 음성 (초) | 단어 | 판정 | 점수 최소 | 점수 중앙 | 정렬 시간 (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| K1 | ko | 7.12 | 8 | ok | 0.824 | 0.912 | 32080.9 |
| K2 | ko | 6.96 | 10 | ok | 0.719 | 0.929 | 33103.6 |
| K3 | ko | 7.60 | 12 | ok | 0.812 | 0.894 | 35961.8 |
| K4 | ko | 6.64 | 9 | ok | 0.692 | 0.841 | 33570.0 |
| K5 | ko | 12.16 | 19 | align_low_confidence | 0.0 | 0.75 | 56005.8 |
| K6 | ko | 6.88 | 10 | ok | 0.709 | 0.936 | 31599.5 |
| K7 | ko | 4.56 | 6 | ok | 0.496 | 0.857 | 28822.0 |
| K8 | ko | 15.20 | 19 | ok | 0.616 | 0.883 | 80426.7 |
| E1 | en | 6.32 | 14 | ok | 0.633 | 0.831 | 12691.6 |
| E2 | en | 3.36 | 8 | ok | 0.697 | 0.829 | 9104.2 |
| E3 | en | 3.04 | 8 | ok | 0.783 | 0.896 | 6651.1 |
| E4 | en | 1.92 | 5 | ok | 0.832 | 0.889 | 5950.2 |

정렬 시간은 두 번 실행의 합임. 12줄 중 11줄이 구절 범위를 만들었고, K5 한 줄이 낮은 신뢰도로 문장형 자막 대상이 됨. 실패 판정은 `align_failed`, `align_missing_words`, `align_unavailable` 모두 0줄임.

- 한국어 8줄의 정렬 시간 합은 331,570.3 ms, 영어 4줄은 34,397.1 ms임.
- model load는 영어 36,878.7 ms, 한국어 7,095.0 ms임. cache가 데워진 상태의 값임.
- 실행 전체 wall time은 413,446.5 ms, peak RSS는 1,782,693,888 bytes (1,700.1 MiB)임.

## 정확도 관찰

- 109개 단어(한국어 74, 영어 35)가 모두 시작과 끝 시간을 가짐. 두 번 정렬한 단어 시간은 12줄 모두 같았음.
- 통과한 11줄의 구절 수는 화면 글의 구절 수와 같음. 화면 글의 비어 있지 않은 문자는 모두 구절 범위 안에 들어감.
- 첫 단어 시작은 11줄에서 유성 구간 시작과 -10~101 ms 차이였음. K5는 1,232 ms 차이였고, 원인은 음절로 읽은 코드명 세 개가 0.0점으로 정렬되지 않은 것임.
- 마지막 단어 끝은 한국어 8줄이 음성 끝과 같았고, 영어 4줄은 60~161 ms 일찍 끝났음.
- 구절 범위 예시는 K4 `가격은 12,500원이고,` 80~2,869 ms, `성공률은 97.3퍼센트입니다.` 3,531~6,640 ms임.
- 영어 통화 줄 E2 `The price is $12.50.`은 40~3,199 ms, 코드명 줄 E3 `Is the CPU version fast enough?`는 141~2,879 ms로 화면 글 범위가 말할 글 단어에 붙음.
- K5는 `씨`, `피`, `지` 세 음절이 0.0점이고 나머지 단어 중앙값은 0.75임. 구절 범위를 만들지 않고 `align_low_confidence`로 끝남.
- 사람이 듣고 만든 기준 시간은 없음. 정확도는 단어 점수, 시간 순서와 경계, 두 번 실행의 일치로 판정함.

## 실패 판정 규칙

| 조건 | 판정 |
| --- | --- |
| 정렬기 예외, 단어 시간이 순서를 어김 | align_failed |
| model load 실패 | align_unavailable |
| 시간이 없는 단어, 말할 글 단어 수와 결과 단어 수 불일치 | align_missing_words |
| 화면 글 단어에 대응하는 말할 글 단어가 없음. 숫자·통화·대문자 코드명·문자 체계 차이만 치환으로 인정 | align_missing_words |
| 화면 글과 말할 글의 구절 수 불일치, 구절 시간이 음성 밖이거나 겹침 | align_missing_words |
| 단어 점수가 0.25 미만이거나 점수 없음 | align_low_confidence |

- 판정 우선순위는 `align_failed`, `align_missing_words`, `align_low_confidence` 순임.
- 실패한 줄은 구절 범위를 만들지 않음. 제품에서는 그 줄이 문장형 자막이 됨.
- 문턱 0.25는 한 곳(`mapping.LOW_CONFIDENCE_SCORE`)에 있고, 결과 JSON에 모든 단어 점수가 있어 다시 판정할 수 있음.

## 후보 동시 설치

`install_matrix.py`가 후보 요구 사항과 `whisperx==3.8.6`을 한 환경으로 해석함. wheel은 내려받지 않음. 결과는 `results/install-matrix.json`에 있음.

| 후보 | x86_64 Linux | aarch64 Linux | 원인 |
| --- | --- | --- | --- |
| qwen3-tts-0.6b | 불가 | 불가 | torch 2.7.1+cpu URL 고정, WhisperX는 torch 2.8.x를 요구 |
| qwen3-tts-1.7b | 불가 | 불가 | torch 2.7.1+cpu URL 고정, WhisperX는 torch 2.8.x를 요구 |
| moss-tts-nano-100m | 불가 | 불가 | huggingface-hub 2.4.0 고정, WhisperX는 huggingface-hub<1.0.0을 요구 |
| chatterbox-multilingual-v3 | 불가 | 불가 | huggingface-hub 2.4.0 고정, WhisperX는 huggingface-hub<1.0.0을 요구 |

- WhisperX 단독 해석은 두 platform에서 성공함. x86_64는 torch 2.8.0, torchcodec 0.7.0, aarch64는 torch 2.8.0, torchcodec 0.17.0, 둘 다 huggingface-hub 0.36.2, transformers 4.57.6임.
- 후보의 공유 pin 두 개(huggingface-hub, tokenizers)를 WhisperX 범위로 옮긴 경우를 같은 조건으로 해석함. MOSS와 Chatterbox는 두 platform에서 torch 2.8.0, huggingface-hub 0.36.2, tokenizers 0.22.2로 풀림.
- Qwen 두 후보는 공유 pin을 옮겨도 torch 고정 때문에 풀리지 않음. torch 2.8 build로 올리는 것은 이 후보의 시험 범위 밖임.

## 설치 크기와 모델 bytes

| 항목 | bytes | MiB |
| --- | --- | --- |
| WhisperX 환경, 설치 직후 | 1,254,821,544 | 1,196.7 |
| WhisperX 환경, 첫 실행 뒤 | 1,343,734,188 | 1,281.5 |
| ONNX TTS 환경 | 155,302,657 | 148.1 |
| 한국어 정렬 model | 1,266,768,843 | 1,208.1 |
| 영어 정렬 model | 377,664,473 | 360.2 |
| ONNX TTS model 디렉터리 두 개 | 763,213,633 | 727.9 |

- 환경 bytes는 가상 환경 디렉터리의 파일 크기 합이고, model bytes는 cache 파일 크기 합임. bytecode cache가 생기면 환경 크기가 늘어남.
- 정렬 model 두 개 합은 1,644,433,316 bytes (1,568.3 MiB)임.
- ONNX TTS model은 합성 입력을 만드는 데만 쓰고 제품 정렬 경로에는 들어가지 않음.

## 결정 gate

- 정렬은 11줄이 구절 범위를 만들고 한 줄이 낮은 신뢰도로 문장형 자막이 됨. 정렬기 자체는 실패 없이 돌았으므로 언어별 문장형 fallback을 전제로 쓰는 판정은 가능함.
- 선택 후보 동시 설치는 게시된 요구 사항 그대로는 네 후보 모두 불가함. MOSS와 Chatterbox는 공유 pin 두 개를 옮기면 가능해지고, Qwen 두 후보는 torch build를 올려야 함.
- 따라서 "정렬 통과와 선택 후보 동시 설치 가능"은 후보 요구 사항을 고친 뒤에 확정됨. 고치지 않으면 설치는 충돌 상태이고 정렬은 `align_unavailable` fallback이 됨.
- Windows 수치는 이번 측정에 없음. workflow를 수동 실행하고 `windows` 입력을 켜면 같은 절차가 windows-latest에서 돎.

## 실행 환경 주의

- NLTK는 data 디렉터리가 다른 계정에서 쓸 수 있으면 기본 경로를 거부함. 이 호스트에서는 공유 home 아래 기본 경로가 거부되어 `punkt_tab`을 private 디렉터리에 미리 받은 뒤 `NLTK_DATA`로 지정해야 정렬이 돌았음. 첫 실행이 `LookupError`로 실패한 원인임.
- 배포 runtime은 `punkt_tab`을 동봉하거나 private data 경로를 보장해야 함. 그렇지 않으면 정렬이 매번 `align_failed`로 떨어짐.
