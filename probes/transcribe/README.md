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

- `audio/ko.wav`와 `audio/en.wav`가 기본 입력이다. 길이가 20~40초가 아니거나 파일이 없으면 harness 오류다.
- 같은 이름의 `.txt`가 기준 글이다. 없으면 전사만 하고 WER은 재지 않는다.
- 두 파일의 출처와 라이선스는 [audio 안내](audio/README.md)에 있다.
- 다른 음성으로 재려면 `--audio-dir`에 같은 이름의 `.wav`와 `.txt`를 둔다.

## 결과

`result.json`의 `status`는 `ok`, `partial`, `failed`, `dry_run` 중 하나다.

- `ok`: 모든 언어의 전사가 끝났다.
- `partial`: 일부 언어가 실패했다.
- `failed`: 모든 언어가 실패했거나 model을 load하지 못했다.
- `dry_run`: stub 실행이다.

시험 대상의 실패인 `RuntimeError`와 `ValueError`는 `runs[].failure`에 적고 process는 0으로 끝난다. 그 밖의 예외, 음성 파일 문제, model download 실패는 `status`가 `harness_error`이고 process는 2로 끝나 workflow를 실패시킨다. 수치는 [RESULT.md](RESULT.md)의 표에 옮긴다.

## 고정 버전

[requirements.txt](requirements.txt)가 probe 환경을 고정한다. faster-whisper 1.2.1과 그 직접 의존성을 2025년 배포본으로 맞춰 Python 3.11의 Linux x64와 Windows x64 wheel 조합을 만든다. 설치된 전이 버전은 결과의 `runtime`에 남는다.
