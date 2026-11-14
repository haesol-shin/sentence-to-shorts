# TTS 후보 비교 결과

네 후보를 같은 대본으로 합성해 CPU에서의 속도와 메모리, 그리고 들을 수 있는 음성 묶음을 남긴다. 수치는 GitHub Actions 러너에서 잰 값만 적고 추정값은 적지 않는다.

## 측정 규칙

- cold start는 새 프로세스를 띄운 시각부터 모델이 준비된 시각까지다. `result.json`의 `cold_start_ms`이며 `PROBE_START_MS`를 프로세스 시작 시각으로 쓴다.
- 첫 WAV는 새 프로세스를 띄운 시각부터 첫 합성이 WAV 파일을 다 쓴 시각까지다. `first_wav_ms`에 적는다. 모델 준비 뒤부터의 합성 시간은 `warmup_synth_ms`에 따로 적는다. 이 실행은 warmup이며 RTF 집계에서 뺀다.
- warmup 한 번 뒤 문장마다 세 번 합성한다. `texts[].runs`에 세 번의 wall time과 WAV 길이가 있고, 성공한 실행만 집계한다.
- 문장 RTF는 합성 wall time을 저장한 WAV 길이로 나눈 값이다. 전체 RTF는 전체 합성 시간의 합을 전체 WAV 길이의 합으로 나눈 값이며 `rtf`에 적는다.
- peak RSS는 측정 프로세스와 자식 프로세스의 RSS를 50ms 간격으로 더해 얻은 최댓값이다. `peak_rss_bytes`에 적는다.
- 모델 bytes는 내려받은 snapshot 파일 크기의 합, 환경 bytes는 가상 환경 디렉터리 크기다.
- thread 수, CPU 모델, RAM, OS, Python 버전은 `result.json`의 `thread`와 `host`에 적는다.
- install과 모델 다운로드는 30분 제한을 두고 제한을 넘으면 결과 파일에 timeout으로 적는다.
- 시험 대상의 실패와 timeout은 `result.json`에 적고 workflow는 성공으로 끝낸다. workflow 실패는 harness 오류만 뜻한다. 상태는 `ok`, `partial`, `failed` 중 하나이며 `partial`은 일부 문장만 실패한 경우다.
- 청취 묶음은 성공한 WAV를 -16 LUFS로 맞추고 peak를 -1 dBFS 아래로 제한한다. 0.4초보다 짧은 음성은 더 짧은 BS.1770 block으로 재고, 두 조건을 함께 맞추지 못하면 `target_met`을 false로 두고 실측값을 key에 적는다.
- 후보 이름은 후보마다 글자 하나로 바꾸고 OS별 파일은 같은 글자 아래 하위 폴더에 둔다. 대응표는 이 문서에 적지 않고 별도 artifact `listening-key`에만 둔다.

## 후보 × OS

| 후보 | OS | 상태 | cold start (ms) | 첫 WAV (ms) | RTF | peak RSS (MiB) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3-tts-0.6b | ubuntu-24.04 | 실행 대기 | | | | | |
| qwen3-tts-1.7b | ubuntu-24.04 | 실행 대기 | | | | | |
| moss-tts-nano-100m | ubuntu-24.04 | 실행 대기 | | | | | |
| chatterbox-multilingual-v3 | ubuntu-24.04 | 실행 대기 | | | | | |
| qwen3-tts-0.6b | windows-latest | 설치 작업 뒤 실행 | | | | | |
| qwen3-tts-1.7b | windows-latest | 설치 작업 뒤 실행 | | | | | |
| moss-tts-nano-100m | windows-latest | 설치 작업 뒤 실행 | | | | | |
| chatterbox-multilingual-v3 | windows-latest | 설치 작업 뒤 실행 | | | | | |

결과는 이 PR의 Actions 실행 artifact에서 채운다.

Windows 실행은 설치 작업이 끝난 뒤 `workflow_dispatch` 입력 `windows`를 켜서 돌리고, 이 표에 행을 더한다. pull request 실행은 `ubuntu-24.04`만 돌린다.

## 화자

| 후보 | 한국어 화자 | 영어 화자 | 비고 |
| --- | --- | --- | --- |
| qwen3-tts-0.6b | Sohee | Ryan | CustomVoice preset |
| qwen3-tts-1.7b | Sohee | Ryan | CustomVoice preset |
| moss-tts-nano-100m | Ava | Ava | 한국어 preset이 없어 같은 preset을 쓴다 |
| chatterbox-multilingual-v3 | default_voice | default_voice | 묶음 reference 하나뿐이라 한국어도 같은 reference로 읽는다 |

모델 checkpoint와 codec revision의 원본은 후보별 `models.json` 하나다. `synth.py`는 그 파일에서 checkpoint와 revision을 읽고, `result.json`의 `models`도 같은 파일에서 만들어진다. 이 문서는 SHA를 따로 적지 않는다.

## 실패와 한계

- 실패 사유는 각 artifact의 `result.json`에 단계(`install`, `load`, `synthesize`)와 코드로 남는다. 이 표에는 artifact를 읽은 뒤 같은 내용을 옮긴다.
- MOSS와 Chatterbox 경로는 upstream Python 패키지의 text normalization을 쓰지 않는다. 숫자와 단위가 든 K3, K4, K5의 발음은 이 경로의 실제 동작이며 제품의 normalization 결정과 별개다.
- Chatterbox는 preset 화자 모델이 아니라 reference audio가 필요한 모델이다. 묶음에 들어 있는 `default_voice.wav` 하나를 두 언어에 쓴다.
- 이 호스트는 aarch64라서 후보 환경을 만들지 않는다. 모든 수치는 x64 GitHub Actions 러너에서만 나온다.
