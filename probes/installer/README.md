# 사용자별 설치 probe

관리자 권한 없는 Windows 사용자별 설치 exe와 Linux tarball을 만들고, 한글과 공백이 든 합성 사용자 경로에서 빈 FastAPI 앱을 띄우는지 잰다. probe 코드는 제품 코드가 아니며 제품 의존성과 lockfile에 넣지 않는다.

## 구성

| 경로 | 역할 |
|---|---|
| `run_probe.py` | runtime을 받고 bundle을 만들고 installer와 tarball을 빌드하고 설치와 시작을 잰다. 긴 경로에서 설치와 시작을 한 번 더 돈다 |
| `harness.py` | 경로, tar, template, 결과 파일처럼 시험 가능한 부분 |
| `launcher.py` | 인자 없이 빈 port를 골라 server를 띄우고 `/health`가 뜬 뒤 옆의 `port.json`을 쓰고 browser를 연다 |
| `app/health_app.py` | `/health`만 있는 FastAPI 앱. server의 Python 절대 경로를 돌려준다 |
| `start.sh` | Linux tar의 진입점. 설치된 환경의 Python으로 launcher를 실행한다 |
| `templates/` | Inno Setup과 NSIS script 원본. 값은 실행할 때 채운다 |
| `runtime.json` | Python 3.11.18 install_only 배포 파일과 SHA-256, uv, app version 고정 |
| `requirements.in`, `requirements.txt` | 빈 앱의 직접 의존성과 hash 포함 설치 목록 |
| `RESULT.md` | 결과 표와 측정 규칙 |
| `tests/` | network와 x64 없이 도는 단위 시험 |

## 로컬 확인

```sh
python -m unittest discover -s probes/installer/tests -v
python -m py_compile probes/installer/harness.py probes/installer/run_probe.py probes/installer/launcher.py probes/installer/app/health_app.py
python probes/installer/run_probe.py --dry-run --python <3.11 interpreter> --output probes/installer/out
```

`--dry-run`은 이 호스트의 Python으로 hash 목록을 설치한 뒤 package 파일만 bundle에 넣고, 이 호스트 interpreter를 bundle의 Python 자리에 연결하고, tar로 묶고, 한글과 공백이 든 작업 폴더에 풀고, build 폴더를 지우고 인자 없는 `start.sh`로 앱을 띄워 `/health`를 확인한다. 긴 경로 설치와 시작도 같은 실행에서 확인한다. x64 배포 파일을 받지 않으므로 `runtime.download`와 `runtime.extract`는 건너뛰고, 새 계정도 만들지 않는다. 이 결과는 실측이 아니며 [RESULT](RESULT.md) 표에 옮기지 않는다.

`--strict`를 붙이면 harness 오류를 종료 코드 2로 돌려준다. workflow는 이 값을 쓴다.

## 실행

pull request를 열면 [workflow](../../.github/workflows/probe-installer.yml)가 `ubuntu-24.04`에서 harness 시험과 probe를 돌리고 `probe-installer-linux-x86_64` artifact로 `result.json`과 `summary.md`를 올린다. `windows-latest`는 `workflow_dispatch`의 `windows` 입력이 true일 때만 matrix에 들어간다. Windows 실행은 설치 작업 뒤로 미룬다.

## 고정 값

- Python은 python-build-standalone의 CPython 3.11.18 install_only다. Windows x64와 Linux x64가 같은 배포 방식을 쓴다. SHA-256은 배포 release의 `SHA256SUMS`와 자산 digest에서 확인해 [runtime.json](runtime.json)에 적었다.
- `requirements.txt`는 `fastapi`와 `uvicorn`의 hash 포함 목록이다. `poetry export`가 만드는 것과 같은 `name==version --hash=sha256:...` 모양이며, probe에는 Poetry가 없으므로 같은 모양을 uv로 만들었다. 다시 만드는 명령은 `uv pip compile --universal --generate-hashes --python-version 3.11 probes/installer/requirements.in --output-file probes/installer/requirements.txt`다.
- 설치 목록은 `uv pip sync --require-hashes`로만 쓴다. uv 버전의 원본은 [runtime.json](runtime.json)이고 workflow가 이 값을 읽어 설치한다.

## 작업 폴더

- `--work-dir`을 주지 않으면 `RUNNER_TEMP` 아래에 `installer probe` 폴더를 만든다. 폴더 이름과 그 아래 홈 폴더에 한글과 공백을 둔다.
- 결과는 `--output`에만 쓰고, 실패한 실행도 `result.json`과 `summary.md`를 남긴다.
- `--keep`은 작업 폴더를 지우지 않는다. Linux에서 만든 합성 계정은 runner가 사라질 때 함께 사라진다.
- 시작은 `start.sh`와 시작 바로가기 모두 인자 없이 한다. launcher는 옆의 `port.json`에 port를 쓰고 browser를 연다. headless runner에서는 `browser_opened` 값만 남고 실제 창은 확인하지 않는다.
- bundle에는 동봉 Python, package 폴더, 앱을 넣는다. build 때 만든 가상 환경은 넣지 않고 package 파일만 꺼낸다. launcher와 `start.sh`는 그 package 폴더를 `PYTHONPATH`로 넘긴다.
