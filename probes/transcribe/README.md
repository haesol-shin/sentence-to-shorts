# 전사 probe

faster-whisper small int8을 CPU에서 돌려 한영 전사 시간, peak RAM, 모델 bytes, 단어 오류를 잰다. 이 디렉터리는 probe 코드이고 제품 의존성과 제품 lockfile에 들어가지 않는다.

## 실행

pull request를 열면 [workflow](../../.github/workflows/probe-transcribe.yml)가 `ubuntu-24.04`에서 harness를 돌리고 OS별 artifact로 `result.json`을 올린다. `windows-latest` 항목은 `windows` 입력을 true로 준 수동 실행에서만 matrix에 들어간다.

개발 기기가 aarch64라서 x64 수치는 Actions 실행에서만 나온다. 로컬에서는 stub으로 경로만 확인한다.

```sh
python probes/transcribe/harness.py run --out "$TMPDIR/result.json" --stub
python -m unittest discover -s probes/transcribe/tests -v
```

## 시험 음성

- `probes/transcribe/audio/<언어>.wav`가 있으면 시험 음성으로 쓴다.
- 같은 이름의 `.txt`가 있으면 기준 글로 쓰고 WER을 잰다.
- 파일이 없으면 harness가 24초 합성 파형을 만든다. 음절 모양의 파형이고 단어가 없으므로 WER은 재지 않는다. 시간과 메모리 수치는 이 파형으로도 잰다.

## 결과

`result.json`의 `status`는 `ok`, `partial`, `failed`, `dry_run` 중 하나다.

- `ok`: 모든 언어의 전사가 끝났다.
- `partial`: 일부 언어가 실패했다.
- `failed`: 모든 언어가 실패했거나 model을 준비하지 못했다.
- `dry_run`: stub 실행이다.

시험 대상의 실패는 `runs[].failure`에 적고 process는 0으로 끝난다. harness 오류는 `status`가 `harness_error`이고 process는 2로 끝나 workflow를 실패시킨다. [RESULT.md](RESULT.md)는 표 머리글과 측정 규칙만 두고 수치는 artifact에서 옮긴다.

## 측정 항목

| 필드 | 뜻 |
| --- | --- |
| `settings` | model, compute type, thread, beam, vad, fixture 길이 |
| `environment` | OS, CPU 수, RAM, python, runner 정보, commit |
| `runtime` | 설치된 package 버전 |
| `model` | model bytes, revision, file 수, download 시간, load 시간 |
| `runs[].elapsed_ms` | `transcribe` 호출 전체 시간, generator 소비 포함 |
| `runs[].rtf` | 전사 시간을 오디오 길이로 나눈 값 |
| `runs[].peak_rss_bytes` | 그 실행까지의 process 최대 상주 메모리 |
| `runs[].word_error` | 기준 글과 전사의 단어 편집 거리와 비율, 못 재면 `reason` |

## 고정 버전

[requirements.txt](requirements.txt)가 probe 환경을 고정한다. faster-whisper 1.2.1과 그 직접 의존성을 2025년 배포본으로 맞춰 Python 3.11의 Linux x64와 Windows x64 wheel 조합을 만든다. 설치된 전이 버전은 결과의 `runtime`에 남는다.
