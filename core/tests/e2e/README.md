# 실제 공급자 경로 수락 시험

일반 시험은 외부 공급자를 호출하지 않는다. 실제 수락은 `APP_PROFILE=dev`와 정확한 `-m realllm` 선택을 모두 요구한다. fixture profile이나 녹화 응답을 실제 생성 성공으로 보고하지 않는다.

## 실행 준비

- `core/config/app.yaml`의 공급자 표는 바꾸지 않는다. dev LLM은 `openai_compat`, 참고 분석의 downloader·transcriber·media는 `default`를 사용한다. TTS도 표에 선택된 엔진을 그대로 사용하며 현재 `fixed_wav` 결과를 자연스러운 음성 검수로 간주하지 않는다.
- 선택된 기본 aligner 구현이 먼저 필요하다. 미구현 상태에서는 `selected_default_aligner` fixture가 명확한 실패 사유를 남긴다. fixture aligner나 가짜 단어 시간으로 대체하지 않는다.
- `APP_LLM_BASE_URL`과 haiku·sonnet alias의 model ID를 준비한다. alias 값은 읽기 전용 설정 또는 시험용 `APP_LLM_MODEL_HAIKU`, `APP_LLM_MODEL_SONNET`으로 지정한다. 시험용 override는 파일을 변경하지 않는다.
- 키가 필요한 endpoint는 기존 OS keyring을 쓰거나 `APP_LLM_KEY_ENV`에 키를 보관한 환경변수의 이름을 지정한다. 키가 없는 endpoint도 지원한다. 키를 명령 인자나 증거에 기록하지 않는다.
- `APP_MODEL_DIR`과 `APP_RUNTIME_DIR`에 검증된 모델과 플랫폼에 맞는 ffmpeg·다운로더 runtime을 준비한다. 시험은 설치·다운로드하거나 PATH 실행 파일로 대체하지 않는다. data와 cache는 실행별로 checkout의 `.local/real-e2e/` 아래 격리한다.
- `E2E_REFERENCE_MP4`는 팀이 만든 합성 영상 파일이다. `E2E_ALLOWED_REFERENCE_URL`은 다운로드 권한이 있는 공개 허용 링크 한 개, `E2E_BLOCKED_REFERENCE_URL`은 로그인 없이 접근할 수 없어야 하는 링크 한 개다. 참고 자료는 기본 포맷과 다른 분석 가능한 설정을 포함해야 한다. 로그인·쿠키·보호 조치 우회는 사용하지 않는다.
- `E2E_EVIDENCE_DIR`은 checkout 밖의 아직 존재하지 않는 비공개 `evidence/I2a/` 디렉터리다. 반복 실행은 다른 부모 경로를 사용한다. 기존 증거를 덮어쓰지 않는다.

준비한 환경에서 `core/`를 작업 디렉터리로 실행한다.

```sh
APP_PROFILE=dev poetry run pytest tests/e2e -m realllm -q
```

x64 media 실행과 실제 endpoint 실행은 각각 해당 실행 환경에서 확인한다. 문법 검사나 오프라인 회귀 시험 통과를 실제 공급자 수락 통과로 합치지 않는다.

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
