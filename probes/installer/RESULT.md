# 사용자별 설치 실측

관리자 권한이 필요 없는 Windows 사용자별 설치 exe와 Linux tarball이 한글, 공백, 긴 경로에서 빈 FastAPI 앱을 띄우는지 잰다. probe 코드는 제품 코드가 아니며 제품 의존성과 lockfile에 넣지 않는다. 수치는 같은 PR의 Actions 실행에서만 옮기고 없는 값을 추정하지 않는다.

## 실행

- pull request는 [workflow](../../.github/workflows/probe-installer.yml)의 `ubuntu-24.04` 작업만 돌린다.
- `windows-latest` 항목은 `workflow_dispatch`의 `windows` 입력이 true일 때만 돈다. Windows 실행은 설치 작업 뒤로 미룬다.
- 실행마다 `result.json`과 `summary.md`를 OS별 artifact로 올린다. 이름은 `probe-installer-linux-x86_64`와 `probe-installer-windows-x86_64`다.
- harness만 다시 돌리는 로컬 명령은 [안내](README.md)에 있다. 그 결과는 x64 실측이 아니므로 아래 표에 옮기지 않는다.

결과는 이 PR의 Actions 실행 artifact에서 채운다.

## 측정 규칙

- 표의 행은 artifact의 `result.json`에서 그대로 옮기고, artifact를 남긴 workflow 실행 id와 commit을 「실행」 표에 적는다.
- 모든 시험은 `checks`에 `pass`, `fail`, `skipped` 중 하나로 남는다. 시험 대상의 실패는 결과이고 step은 성공으로 끝난다. harness 오류만 workflow를 실패시킨다.
- `download_bytes`는 고정한 python-build-standalone 배포 파일의 실제 bytes다. `runtime.download`가 SHA-256과 함께 확인한다.
- `compressed_bytes`는 Linux tar.gz와 Windows setup exe의 bytes다. 압축 다운로드가 아니라 빌드 산출물 크기다.
- `installed_bytes`는 설치 폴더 아래 파일 크기 합이다. 긴 경로 시험 파일과 실행 로그는 세지 않는다.
- `install_seconds`는 Linux에서 설치 폴더 생성과 tar 압축 해제 구간, Windows에서 installer 종료까지다. 다운로드, 빌드, 시작 시간은 넣지 않는다.
- `start_seconds`는 `start.sh`나 시작 바로가기를 띄운 순간부터 `/health` 첫 200까지다. 빈 port 선택과 server 기동을 포함한다.
- 새 계정은 이름과 홈 경로에 한글과 공백이 있는 합성 값이다. Linux login 이름에는 공백을 쓸 수 없어 한글 이름과 공백이 든 홈 경로를 쓴다. 차이는 `user.difference`에 남는다. 실제 새 계정 시험을 못 하면 `USERPROFILE`과 `LOCALAPPDATA`, `HOME`을 한글·공백 경로로 바꾼 실행으로 대신하고 `user.created`에 false를 남긴다.
- 긴 경로는 설치 폴더 아래 240자 경로에 파일을 쓰는 것으로 확인한다. 300자 경로 시도는 `path.long`에 기록만 하고 gate로 삼지 않는다. 260자 초과는 OS 정책과 manifest에 달려 있다.
- PATH의 Python으로 우연히 성공했는지 가르기 위해 `/health`가 `sys.executable`과 `base_prefix`를 돌려준다. server가 보고한 실행 경로와 base 경로가 설치 폴더 안이어야 한다. PATH에서 찾은 Python 경로도 `python.not_from_path`에 함께 남긴다.
- 고정 값은 [runtime.json](runtime.json)에 있다. Python은 3.11.18 install_only 배포 파일이고 Windows x64와 Linux x64가 같은 배포 방식을 쓴다.

## 시험 항목

| check | 확인 |
|---|---|
| `runtime.download` | 고정 배포 파일을 내려받고 SHA-256이 manifest와 같다 |
| `runtime.extract` | 배포 파일을 풀고 동봉 Python이 절대 경로에서 3.11.18을 보고한다 |
| `env.venv` | 동봉 Python으로 환경을 만들고 그 환경의 Python이 동작한다 |
| `env.requirements` | `uv pip sync --require-hashes`가 고정 목록을 설치하고 fastapi와 uvicorn을 import한다 |
| `bundle.app` | 빈 앱, launcher, `start.sh`가 bundle에 들어간다 |
| `archive.build` | Linux tar.gz 또는 Windows Inno Setup exe를 만든다 |
| `archive.check` | tar가 실행 권한을 보존하거나 installer script가 사용자 권한과 `localappdata` 경로를 쓴다 |
| `install.user` | 한글·공백 합성 계정을 만들거나 대체 실행과 차이를 남긴다 |
| `install.apply` | 출력 없이 설치하고 설치 폴더와 크기를 잰다 |
| `shortcut.target` | `start.sh` 실행 권한 또는 시작 바로가기 대상이 설치 폴더의 launcher다 |
| `app.start` | launcher가 빈 port를 골라 server를 띄우고 port file을 쓴다 |
| `app.health` | `GET /health`가 200이고 보고한 Python 경로가 설치 폴더 안이다 |
| `python.not_from_path` | server가 PATH의 Python이 아닌 설치된 Python을 썼다 |
| `path.long` | 설치 폴더 아래 긴 경로에 파일을 쓰고 읽는다 |
| `app.stop` | launcher와 server를 종료한다 |

## 결과

### 실행

| OS | runner | artifact | 실행 id | commit |
|---|---|---|---|---|
| linux-x86_64 | ubuntu-24.04 | probe-installer-linux-x86_64 | 미측정 | 미측정 |
| windows-x86_64 | windows-latest | probe-installer-windows-x86_64 | 미측정 | 미측정 |

### 수치

| OS | 압축 bytes | 설치 후 bytes | 설치 시간 (초) | 시작 시간 (초) | 새 계정 |
|---|---|---|---|---|---|
| linux-x86_64 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 |
| windows-x86_64 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 |

### 시험

| OS | check | status | 측정값 | 비고 |
|---|---|---|---|---|
| linux-x86_64 | 15개 | 미측정 | 미측정 | artifact의 `checks`에서 옮긴다 |
| windows-x86_64 | 15개 | 미측정 | 미측정 | 설치 작업 뒤에 돌린다 |

## 수락 증거

- 양 OS에서 새 사용자로 설치한 뒤 `GET /health`가 200이다. `app.health`가 이 값을 남긴다.
- server가 보고한 `sys.executable`과 `base_prefix`가 설치 폴더 안이다. PATH에서 찾은 Python 경로는 다르다. `python.not_from_path`가 두 값을 함께 남긴다.
- Linux tar는 `start.sh`와 동봉 Python의 실행 권한을 보존한다. `archive.check`가 tar member mode를 남긴다.
- Windows 시작 바로가기는 설치 폴더의 `pythonw.exe`로 `launcher.py`를 실행한다. `shortcut.target`이 대상과 인자를 남긴다.

## 결정 gate

- 통과하면 제품 installer 작업이 같은 방식으로 실제 앱을 묶는다.
- Inno Setup이 실패하면 NSIS의 `RequestExecutionLevel user`로 같은 시험을 하고 제품 installer 작업이 그 방식을 쓴다.
- 관리자 권한을 요구하는 방식은 gate를 통과해도 쓰지 않는다.

## 확인하지 못한 것

- SmartScreen과 Defender의 실제 차단 여부는 runner에서 확인할 수 없다. 이 확인은 별도의 실기기 확인으로 남긴다.
- Windows 실행은 설치 작업 전까지 돌리지 않는다. 표의 Windows 행은 그때 채운다.
- 260자 초과 경로는 OS 정책과 실행 파일 manifest에 달려 있어 이 probe의 gate가 아니다. 240자 경로와 300자 시도만 기록한다.
- 서명, 자동 갱신, 제거는 이 probe 범위 밖이다.
- launcher의 browser 열기는 headless runner에서 확인하지 않는다. probe는 `--no-browser`로 시작하고, 시작 바로가기의 대상과 인자만 확인한다.
