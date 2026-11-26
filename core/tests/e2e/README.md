# 실제 공급자 경로 수락 시험

일반 시험은 외부 공급자를 호출하지 않는다. 실제 수락은 `APP_PROFILE=dev`와 정확한 `-m realllm` 선택을 모두 요구한다. fixture profile이나 녹화 응답을 실제 생성 성공으로 보고하지 않는다.

## 실행 준비

실제 시험 전에 저장소 루트에서 사전 점검을 실행한다. 런타임과 정렬기 설정은 실제 시험과 같은 값을 쓰며, `APP_ALIGN_PYTHON`은 WhisperX를 설치한 별도 환경의 Python 경로로 지정한다.

```sh
cd core
APP_PROFILE=dev poetry run python ../scripts/realpath_preflight.py
```

점검은 앱이 참조하는 런타임 항목의 플랫폼별 lock 파일과 설치된 실행 파일의 버전 응답, 정렬기의 WhisperX import를 검사한다. `APP_LLM_BASE_URL`이 있으면 API 모델 목록과 각 route의 짧은 합성 JSON 응답을 검사한다. 아래의 모델 ID와 `APP_LLM_KEY_ENV`를 같은 방식으로 지정하고, base URL에는 API 경로(`/v1`)까지 포함한다. 앱과 같은 요청 형식과 출력 스키마 검증을 쓰지만, 시험 응답이 유효하다고 해서 게이트웨이가 JSON schema를 강제한다는 뜻은 아니다.

허용된 공개 링크의 해석도 확인하려면 `PREFLIGHT_LINK_1`, `PREFLIGHT_LINK_2`에 링크를 넣는다. 번들 다운로더는 메타데이터만 확인하고 미디어는 받지 않는다. 게이트웨이 주소와 링크가 없는 항목은 각각 `SKIP`으로 표시된다. `FAIL`이 하나라도 있으면 종료 코드는 0이 아니다. 사전 점검은 아래의 실제 생성 시험을 대체하지 않는다.

- `core/config/app.yaml`의 공급자 표는 바꾸지 않는다. dev LLM은 `openai_compat`, 참고 분석의 downloader·transcriber·media는 `default`를 사용한다. TTS도 표에 선택된 엔진을 그대로 사용하며 현재 `fixed_wav` 결과를 자연스러운 음성 검수로 간주하지 않는다.
- `app.yaml`에 선택된 aligner(현재 `whisperx`) 구현이 먼저 필요하다. 시험은 어댑터 기대값을 `app.yaml`에서 읽는다. 준비되지 않으면 `selected_aligner` fixture가 명확한 실패 사유를 남긴다. fixture aligner나 가짜 단어 시간으로 대체하지 않는다.
- `APP_LLM_BASE_URL`과 haiku·sonnet alias의 model ID를 준비한다. alias 값은 `APP_LLM_MODEL_HAIKU`, `APP_LLM_MODEL_SONNET`으로 지정한다. dev profile의 `app/settings.py`가 이 변수를 읽으며 앱과 시험이 같은 설정 경로를 쓴다. 파일은 변경하지 않는다.
- 키가 필요한 endpoint는 기존 OS keyring을 쓰거나 `APP_LLM_KEY_ENV`(dev profile이 읽음)에 키를 보관한 환경변수의 이름을 지정한다. 키가 없는 endpoint도 지원한다. 키를 명령 인자나 증거에 기록하지 않는다.
- 정렬 작업 프로세스는 환경변수 `APP_ALIGN_PYTHON`(정렬 런타임 venv의 python 경로)이 필요하다. 없으면 시험이 `core/align_runtime/.venv`의 python을 찾아 설정한다. 앱을 직접 띄울 때는 직접 지정한다.
- `APP_MODEL_DIR`과 `APP_RUNTIME_DIR`에 검증된 모델과 플랫폼에 맞는 ffmpeg·다운로더 runtime을 준비한다. 시험은 설치·다운로드하거나 PATH 실행 파일로 대체하지 않는다. data와 cache는 실행별로 checkout의 `.local/real-e2e/` 아래 격리한다.
- `E2E_REFERENCE_MP4`는 팀이 만든 합성 영상 파일이다. `E2E_ALLOWED_REFERENCE_URL`은 다운로드 권한이 있는 공개 허용 링크 한 개, `E2E_BLOCKED_REFERENCE_URL`은 로그인 없이 접근할 수 없어야 하는 링크 한 개다. 참고 자료는 기본 포맷과 다른 분석 가능한 설정을 포함해야 한다. 로그인·쿠키·보호 조치 우회는 사용하지 않는다.
- `E2E_EVIDENCE_DIR`은 checkout 밖의 아직 존재하지 않는 비공개 `evidence/I2a/` 디렉터리다. 반복 실행은 다른 부모 경로를 사용한다. 기존 증거를 덮어쓰지 않는다.

준비한 환경에서 `core/`를 작업 디렉터리로 실행한다.

```sh
APP_PROFILE=dev poetry run pytest tests/e2e -m realllm -q
```

x64 media 실행과 실제 endpoint 실행은 각각 해당 실행 환경에서 확인한다. 문법 검사나 오프라인 회귀 시험 통과를 실제 공급자 수락 통과로 합치지 않는다.

## GitHub 러너에서 실행

이 호스트에서 끝낼 수 없는 실제 경로 시험(TTS가 문장마다 120초를 넘긴다)은 `Real main path` workflow가 GitHub 러너에서 돌린다. `workflow_dispatch`로만 시작하며 push와 PR에서는 돌지 않는다.

```sh
gh workflow run real-path.yml --ref main -f ref=main -f os=windows-latest
```

- 입력 `ref`는 시험할 브랜치·태그·커밋(기본 `main`), `os`는 `windows-latest`(기본) 또는 `ubuntu-latest`다. `tests`는 `core/` 기준 pytest node id를 공백으로 나눈 목록이며 기본값은 주 경로 시험과 허용 링크 시험이다.
- 러너는 개발자와 같은 방법(`scripts/dev_setup.py --runtime --models`)으로 런타임·환경·모델을 준비하고 공식 Claude CLI를 설치한 뒤 `APP_PROFILE=dev`, `APP_LLM_ADAPTER=claude_cli`로 `-m realllm` 시험을 실행한다.
- 저장소 secret `CLAUDE_CODE_OAUTH_TOKEN`이 필요하다. 어댑터는 CLI 자식 프로세스에서 이름에 TOKEN·CLAUDE·OAUTH가 든 변수를 모두 지우는 것이 기본이다. workflow가 `APP_CLAUDE_CLI_PASS_OAUTH=1`을 주면 `CLAUDE_CODE_OAUTH_TOKEN` 하나만 통과한다. 로컬에서는 이 변수를 쓰지 않고 CLI 자신의 로그인을 쓴다.
- 비용은 구독 한도에서 나간다. 시험 한 번이 한국어·영어 초안 생성과 참고 분석의 LLM 호출을 모두 쓴다.
- `E2E_ALLOWED_REFERENCE_URL`과 `E2E_BLOCKED_REFERENCE_URL`은 workflow에 고정돼 있다. 링크 호스트가 러너를 막으면(`download_blocked`) 허용 링크 시험은 통과가 아니라 건너뜀으로 기록된다. 이 처리는 `E2E_SKIP_BLOCKED_ALLOWED_LINK=1`일 때만 켜진다.
- 참고 파일 시험(`test_20_synthetic_file_analysis_preserves_user_origins`)은 `E2E_REFERENCE_MP4`가 필요한데 workflow가 파일을 주지 않으므로 기본 `tests`에 넣지 않았다.
- job summary에 시험별 통과·실패·건너뜀과 시간, 단계별 경과 시간, LLM 호출 수가 나온다. 증거 폴더, pytest 로그, 앱 로그는 artifact `real-path-<OS>`로 7일 보관된다. 증거의 mp4는 합성 재료로만 만들어지며 PR에 첨부하지 않는다.

## 검증 범위

- 한국어·영어 한 문장과 합성 재료에서 초안 생성, 직접 입력과 추천 출처, 재료의 고유 사실 반영, 대본 확인 전 preview 금지, 장면 확인 전 generate 금지, 명시 확인 뒤 실제 mp4 다운로드와 digest 검사
- 실제 job usage의 provider·model과 단계별 monotonic 시간, 선택 TTS와 adapter 표 기록
- 같은 주제의 카드 3개에서 서로 다른 이야기 beat 흐름 확인
- 같은 프로젝트의 다음 영상에서 주제·대본·재료·참고·장면 비우기, 고정값 보존과 후보가 있는 변화값, 두 번째 생성 뒤 이전 revision 파일·mp4 불변 확인
- 합성 참고 파일과 허용 링크 분석, `reference` 출처와 직접값 보존 및 사용자 변경, 보호 링크의 `download_blocked` 확인

배경은 다음 영상의 설정 복제와 별도로 `scene_data`에서 실제 테마의 후보 중 선택한다. 시험은 같은 beat의 같은 위치를 비교하고, 후보가 둘 이상이면 이전 배경 반복을 실패시킨다. 현재 `scene_data` 입력에는 이전 영상의 배경 이력이 없어 이력 기반 회피 보장에 공백이 있으며, 실호출 수락에서 확인해야 한다. 후보 포함 여부만으로 변화 성공을 대신하지 않는다.

## 비공개 증거 구조

```text
evidence/I2a/
  summary.md
  events.jsonl
  ko.mp4
  en.mp4
  previous.mp4
  next.mp4
```

각 job 종료와 artifact 다운로드 직후 증거를 갱신한다. `events.jsonl`에는 job 상태·attempt·usage·단계 시작과 끝, artifact SHA-256과 bytes, 시나리오 상태가 있다. `summary.md`는 이 기록의 읽기용 요약이다. 한도·인증·실행 실패가 나도 이미 기록한 성공 단계와 digest를 보존하고 실패를 명시한다. 초기 설정 실패는 출력 파일 없이 사유만 남길 수 있다.

prompt, 대본, 재료, 참고 URL, 전사, 원본 프레임, 키, 쿠키, 원본 공급자 오류는 증거 기록에 넣지 않는다. mp4와 증거는 비공개 수락 자료이며 공개 저장소나 PR에 첨부하지 않는다. 공개 결과에는 실제로 실행한 검사와 미검증 범위만 기록한다.

## 생성 스타일, template, 코드 BGM 수락

`test_real_generated_code.py`는 같은 `live_run`과 증거 폴더를 쓴다. `APP_PROFILE=dev`와 `APP_LLM_BASE_URL`이 없으면 이유를 남기고 건너뛴다. 증거는 `E2E_EVIDENCE_DIR` 옆의 `<폴더 이름>-generated-code` 폴더에 쓴다. 이 폴더도 아직 없어야 하며, 주 경로 시험과 함께 선택해도 폴더가 겹치지 않는다.

```sh
APP_PROFILE=dev poetry run pytest tests/e2e -m realllm -k "style or template or bgm" -q
```

- 시각 차이는 `visual_difference` 이벤트(그룹별 IoU와 얼굴 변경 픽셀 수)에, 실행 안전은 `execution_safety`, `style_reuse`, `bgm_cache`, `bgm_swap` 이벤트에 따로 남는다. 코드와 prompt는 남기지 않는다.
- 형태 기준에 걸린 스타일은 한 번 더 시도하고, 두 번 넘지 못하면 기준을 낮추지 않고 실패로 기록한다.
- 코드 BGM 교체 시험은 clip 재생성 0과 sandbox 호출 0을, 저장 스타일 재사용 시험은 style job 0과 `style_code` 호출 0을 확인한다.
- 참고 파일 기반 스타일 시험은 분석 결과가 요약에 스타일을 담지 않아 `xfail(strict=True)`로 둔다. 앱이 그 연결을 갖추면 이 표시를 지운다.
