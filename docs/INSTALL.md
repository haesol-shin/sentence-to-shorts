# 설치 안내

이 문서는 팀원이 설치 파일을 받아 실행하고 갱신하는 방법을 한 장에 모은 것입니다. Python과 ffmpeg 같은 개발 도구를 따로 설치하지 않습니다.

## 받을 파일

Release 페이지에서 OS에 맞는 파일 하나와 `SHA256SUMS`를 받습니다. Release는 확인이 끝나기 전까지 draft입니다.

| 파일 | 용도 |
| --- | --- |
| `*-windows-x86_64-setup.exe` | Windows 사용자별 설치 파일. 관리자 권한이 필요 없습니다 |
| `*-linux-x86_64.tar.gz` | Linux 압축 파일. 풀면 `start.sh`가 있습니다 |
| 파일 이름 끝이 `-dev`인 것 | 개발 profile. 나머지는 release profile입니다 |
| `*.build-info.json` | 빌드한 commit, lock 해시, runtime manifest digest |
| `SHA256SUMS` | 받은 파일의 SHA-256 |

받은 파일은 실행하기 전에 `SHA256SUMS`와 맞춥니다. Linux는 `sha256sum -c SHA256SUMS --ignore-missing`, Windows는 PowerShell의 `Get-FileHash <파일>` 값을 비교합니다.

## profile

| profile | 사용자 인증 | 용도 |
| --- | --- | --- |
| release | 사용자 자신의 API key. 첫 실행 화면에서 입력합니다 | 배포판 |
| dev | 설정한 OpenAI 호환 endpoint. 공식 Claude CLI는 선택입니다 | 개발 빌드 |

두 파일은 같은 프로그램이고 `dist.json`의 기본 profile만 다릅니다. 환경변수 `APP_PROFILE`이 있으면 그 값이 우선하며, 제공자도 실제 선택한 profile의 설정을 따릅니다. 두 배포물의 `profile_adapters`는 공통 제공자 표 하나에서 생성하며 dev, release, fixture 설정을 모두 담습니다. release는 `anthropic_api`, dev는 `openai_compat`, fixture는 녹화 응답을 사용합니다. dev에서만 `APP_LLM_ADAPTER=claude_cli`로 공식 CLI를 고를 수 있고, endpoint 주소는 환경변수 `APP_LLM_BASE_URL`로 줍니다. 실제 선택한 profile이 dev이면 공식 CLI의 설치, 버전, 로그인 상태를 CLI 자신에게 물어보고, 없으면 공식 설치 안내 주소를 보여 줍니다. release profile에는 이 준비 단계가 없습니다. 앱은 CLI의 인증 파일을 읽지 않습니다.

## 지원 OS와 CPU

실측 결과가 기록된 조합만 지원한다고 적습니다. 설치 시험은 draft Release workflow가 새 사용자와 한글·공백 경로에서 `/api/v1/health` 200을 확인한 결과입니다.

| OS와 CPU | 설치 시험 결과 |
| --- | --- |
| Linux x86_64 | 미측정. workflow 실행 결과가 나오면 옮깁니다 |
| Windows x86_64 | 미측정. Windows 실행은 설치 작업 전까지 미룹니다 |
| 그 밖의 OS와 CPU | 설치 파일이 없습니다 |

## 설치

Windows는 `setup.exe`를 실행합니다. 설치 위치는 사용자 폴더의 `AppData\Local\Programs\<app_id>\<버전>`이고 관리자 권한을 요구하지 않습니다. 설치 파일에는 서명이 없어서 Windows가 경고를 보일 수 있습니다. 관리자 권한으로 실행하거나 보호 기능을 끄지 말고, 경고가 보이면 설치를 멈추고 담당자에게 알려 주세요.

Linux는 원하는 폴더에서 `tar -xzf <파일>`로 풉니다. 푼 폴더가 설치 폴더입니다. 별도 설치 단계가 없습니다.

## 시작

Windows는 시작 메뉴의 앱 이름을 누릅니다. Linux는 푼 폴더에서 `./start.sh`를 실행합니다. 시작하면 비어 있는 포트를 골라 서버를 띄우고 브라우저를 엽니다. 주소의 `#pair=` 뒤 일회용 코드는 브라우저가 서버와 한 번 짝을 맺는 데 쓰이며 5분 뒤 만료됩니다. 브라우저를 열 수 없으면 터미널에 같은 주소를 보여 줍니다.

이미 실행 중이면 새로 띄우지 않고 실행 중인 앱을 브라우저로 엽니다. 탭을 닫았어도 같은 브라우저에 유효한 세션 cookie가 남아 있으면 같은 주소로 다시 접속할 수 있으며, 앱을 재시작할 필요가 없습니다.

Deno, Pyodide, ffmpeg는 설치 파일에 들어 있어서 첫 실행에 내려받지 않습니다. 앱은 PATH의 Python이나 ffmpeg를 쓰지 않고 설치 폴더의 파일만 씁니다. ffmpeg는 GPL-3.0-or-later 빌드이고 라이선스 문구는 설치 폴더의 `licenses`와 `THIRD_PARTY_NOTICES.md`에 있습니다. 같은 릴리스에 `ffmpeg-corresponding-source-<플랫폼>.tar` 자산이 함께 올라가며, 그 안에 FFmpeg 판, 켜 둔 외부 라이브러리의 원본, 빌드 스크립트와 패치, 다시 빌드하는 방법이 들어 있습니다. 모델처럼 설치 파일에 없는 항목은 첫 실행에 runtime manifest의 SHA-256으로 확인하며 받고, 중간에 끊겨도 이어 받습니다. 두 번째 실행부터는 내려받지 않습니다.

휴대폰으로 같은 와이파이에서 접속하려면 `APP_LAN=1`로 시작합니다. 평문 LAN은 합성 자료 시험에만 쓰세요. 접속 코드는 컴퓨터 화면에 보입니다.

## 종료

Windows는 시작 메뉴의 `종료`가 붙은 항목을 누릅니다. Linux는 실행한 터미널에서 Ctrl+C를 누르거나 `./start.sh --stop`을 실행합니다. 종료해도 프로젝트와 모델은 지워지지 않습니다.

## 갱신

새 설치 파일을 받아 같은 방법으로 설치합니다. 새 버전은 새 폴더에 설치되므로 이전 버전은 Windows의 앱 제거 화면이나 Linux의 폴더 삭제로 따로 지웁니다. 프로젝트와 모델은 사용자 데이터 폴더에 있어서 갱신과 제거 뒤에도 남습니다.

## 실패 로그 위치

| 로그 | Windows | Linux |
| --- | --- | --- |
| 앱 로그 | `%LOCALAPPDATA%\<app_id>\data\log\app.log` | `$XDG_DATA_HOME/<app_id>/data/log/app.log`, 없으면 `~/.local/share/<app_id>/data/log/app.log` |
| 시작 로그 | 같은 폴더의 `launcher.log` | 같은 폴더의 `launcher.log` |

앱 로그는 5MB씩 3개를 돌려 씁니다. 로그에는 프롬프트, 대본, 재료, API key, 접속 코드가 들어가지 않습니다. 실패를 알릴 때는 로그의 해당 줄을 붙이고 합성 자료만 쓰세요.

## 삭제

Windows는 설정의 앱 제거로 설치 폴더를 지웁니다. Linux는 푼 폴더를 지웁니다. 사용자 데이터 폴더는 남습니다. 프로젝트와 모델까지 지우려면 위 로그 위치의 `data` 폴더를 직접 지웁니다.
