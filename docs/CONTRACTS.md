# CONTRACTS

이 문서는 모듈 간 데이터·API·job·저장 계약의 원본이다. 제품 동작은 [SPEC](SPEC.md), 용어는 [GLOSSARY](GLOSSARY.md)를 따른다. 「기술 선택」은 구현 세부와 그 이유다. 미확정 구현은 마지막 [열린 질문](#열린-질문)에 둔다.

저장·job 구조의 상태는 [ADR 0007](decisions/0007-persist-storage-and-job-state.md), provider 분리는 [ADR 0003](decisions/0003-separate-llm-providers-and-routing.md), sandbox는 [ADR 0005](decisions/0005-run-generated-code-in-pyodide-deno.md), runtime 동봉은 [ADR 0012](decisions/0012-package-for-windows-and-linux.md)을 따른다.

## 0. 원본 규칙

- schema 원본은 `core/app/schemas/`의 Pydantic 모델이다.
- 저장소 root의 `schemas/*.schema.json`, OpenAPI, `frontend/src/shared/api/generated/`는 원본에서 생성한다.
- 생성물은 손으로 고치지 않는다. CI가 생성 결과와 commit된 파일의 차이를 실패로 처리한다.
- 계약 모델이 저장소에 들어오기 전에는 이 문서가 필드 이름, required, enum, pattern, 범위의 기준이다. 생성 schema는 이 문서와 같아야 한다.
- 기술 선택: 생성한 JSON Schema를 저장소에 commit한다. 이유: 리뷰어와 비Python 소비자가 Python 실행 없이 계약을 읽는다.
- 계약 모델이 들어온 뒤에는 이 문서와 Pydantic 모델이 다르면 Pydantic 모델이 우선한다. 차이는 계약 변경 PR에서 함께 고친다.

## 1. 데이터 문서

문서별 저장 배치는 [열린 질문](#데이터-문서-배치)의 제안이다.

### 1.1 문서 규칙

- 모든 객체는 정의하지 않은 필드를 거절한다. 말투 필드명은 `register`이며 `tone` 필드는 따로 만들지 않는다.
- 앱이 발급하는 ID는 TypeID다. 기술 선택: `<prefix>_<26자 Crockford base32>` 형식이고 접미사 26자는 UUIDv7의 128비트를 소문자 Crockford base32로 적은 값이며 첫 글자는 `0`~`7`이다([TypeID 명세](https://github.com/jetify-com/typeid)). 접두사는 지금 값을 유지한다. 이유: [SPEC 1](SPEC.md#1-범위와-실행-형태)이 여럿 실행의 데이터 구조를 지금 정하고, 여러 기기와 실행 형태의 데이터 저장소에서 만든 ID를 나중에 합칠 수 있기 때문이다.
- 확장 가능한 항목(그림체, 카드, 목소리, BGM, 글꼴, template, 배경, 부위)은 `CatalogId` 문자열이다. 값 검사는 registry 조회로 하고 TypeID 규칙을 쓰지 않는다. 코드 enum에 새 항목을 추가하지 않는다.
- 닫힌 값(말투, 유머, 캐릭터 역할, 자막 표시 모드, job 상태)만 enum이다.
- video revision은 immutable이다. 변경은 새 revision을 쓴다. 과거 revision 파일은 다시 쓰지 않는다.
- 생성 결과는 video 문서에 넣지 않는다. 기술 선택: artifact는 cache key로 index에서 찾고 `VideoBuild`로 보여 준다. 이유: undo가 같은 원본으로 돌아가면 같은 key로 이전 결과를 바로 찾는다.
- 장면의 대사는 `Scene.lines`가 소유한다. `Script`는 원문과 출처만 갖는다.
- `scene_order`의 집합은 `scenes`의 key 집합과 같아야 한다.
- 장면 순서는 `scene_order`만 바꾼다. scene ID는 바꾸지 않는다.
- 다음 영상은 settings를 복사하고 topic, material, reference, script, scenes를 비운다. `derived_from`에 출처를 남긴다. 과거 snapshot은 다음 영상 수정으로 바뀌지 않는다.
- 프로젝트 설정과 영상별 snapshot이 제작 상태의 원본이다. 대화 이력과 요약은 원본을 대신하거나 확정값·lock을 덮지 못한다.
- 프로젝트 기본값은 현재 영상 수정으로 바뀌지 않는다. 프리셋 저장은 명시 요청으로만 한다.

### 1.2 값의 출처와 고정

- `Settings.origins`는 JSON Pointer별 출처를 기록한다.
- 채우는 우선순위는 user, reference, preset, card, llm, default 순서다.
- 낮은 순위의 출처는 높은 순위 값을 덮지 않는다. 덮어야 하면 `ChangePlan`이 `user_value_overwrite`로 확인을 요구한다.
- 대화로 바꾼 값의 출처는 user다.
- `Settings.locks`의 locked 항목은 같은 프로젝트의 다음 영상에서 그대로 복사한다.
- varied 항목은 다음 영상 생성 때 앱이 다른 후보를 고른다. 기술 선택: 후보 선택은 seed가 있는 결정적 함수로 하고 최근 2편의 값을 피한다. 이유: 시험이 재현되고 LLM 호출이 없다.
- lock 항목을 바꾸는 변경은 `lock_change` 확인을 요구한다.

### 1.3 의미 검사

schema 검사 뒤 `services/project`의 의미 검사기가 다음을 거절한다. 오류 코드는 [3.1절](#31-오류-본문)의 `errors[].code`로 돌려준다.

| code | 조건 |
|---|---|
| `unknown_catalog_id` | registry에 없는 ID, 현재 그림체에 없는 에셋·배경·표정·자세 |
| `duplicate_order` | `scene_order` 중복 또는 `scenes`와 집합 불일치 |
| `duplicate_line_id` | 영상 안 line ID 중복 |
| `typewriter_layout` | typewriter인데 template의 `dialog_box`가 false |
| `role_none_character` | character_role none인데 캐릭터 설정이나 배치가 있음 |
| `character_missing` | presenter, subject인데 캐릭터 설정이 없음 |
| `incompatible_part` | `rig.compat`가 허용하지 않는 body와 부위 조합 |
| `highlight_range` | highlight span이 display_text 범위를 벗어나거나 겹침 |
| `reveal_line_unknown` | element나 sfx가 장면에 없는 line을 가리킴 |
| `revision_conflict` | 요청의 base_revision이 head가 아님 (HTTP 409 problem으로 응답하고 `current_revision` 확장 멤버를 함께 돌려준다) |

## 2. 버전과 migration

- 저장 문서(project, video, preset, change, 모든 manifest, timing)는 정수 `schema_version`을 갖는다. 현재 값은 1이다.
- manifest는 추가로 `api_version`을 갖는다. 렌더러 계약 버전이다.
- 기존 문서를 무효로 만들거나 뜻을 바꾸는 변경은 `schema_version`을 올린다.
- 기본값이 있는 선택 필드 추가는 버전을 올리지 않는다.
- migration은 `core/app/storage/migrations/v<N>_to_v<N+1>.py`의 순수 함수 `migrate(doc: dict) -> dict`다.
- 읽을 때 순서대로 적용한다. 원본 revision 파일은 다시 쓰지 않는다. 다음 쓰기에서 새 버전으로 저장한다.
- migration마다 이전 버전 fixture와 기대 결과 fixture를 함께 추가한다.
- 앱보다 높은 `schema_version` 문서는 열지 않는다. API는 422 `unsupported_version` problem과 `found`, `supported` 확장 멤버로 알린다. job 안에서 읽다 만나면 job 오류 `unsupported_version`으로 실패시킨다. 두 enum 모두에 이 코드가 있다.
- plugin과 생성 package의 manifest는 migration하지 않는다. 지원하지 않는 `schema_version`이나 `api_version`은 registry가 등록 전에 거절한다.
- SQLite는 `PRAGMA user_version`과 순서 있는 SQL migration을 쓴다. 적용 전에 `state.db`를 `state.db.bak-<version>`으로 복사한다. 실패하면 원본을 보존하고 앱을 시작하지 않는다.

## 3. HTTP API 공통 규칙

- 기본 경로는 `/api/v1`이다. 빌드한 SPA는 같은 origin의 `/`에서 제공한다.
- GET은 상태를 바꾸지 않는다.
- 인증과 origin 검사는 13절을 따른다. `GET /health`와 `POST /session/pair`만 세션 없이 받는다.
- 영상을 바꾸는 요청은 `base_revision`을 받는다. head와 다르면 409 `revision_conflict` problem과 `current_revision` 확장 멤버를 돌려준다. 서버는 병합하지 않는다. 이미 적용된 계획의 적용 재시도는 4.1절의 예외를 따른다.
- 자원이나 job을 만드는 POST는 `Idempotency-Key` header(8~64자 `[A-Za-z0-9_-]`)를 요구한다.
- 같은 key와 같은 요청 digest는 저장한 응답을 그대로 돌려준다. 같은 key와 다른 digest는 409 `idempotency_mismatch`다. key는 24시간 보관한다.
- 요청 digest는 SHA-256이다. JSON 본문은 canonical JSON(8절 규칙)의 SHA-256이다. multipart 본문은 `file` 파트의 SHA-256과 나머지 필드를 이름 순으로 canonical JSON으로 만든 값을 이어 붙인 문자열의 SHA-256이다. 서버는 업로드를 임시 파일로 받으며 해시를 계산하므로 파일 전체를 메모리에 올리지 않는다. 한도를 넘으면 해시 계산 중에도 413으로 끊는다.
- 같은 영상, 같은 kind, 같은 요청 digest의 활성 job이 있으면 새 job 대신 그 job을 200으로 돌려준다.
- 같은 영상, 같은 kind의 다른 활성 job이 있으면 409 `job_running` problem과 `job_id` 확장 멤버를 돌려준다.
- 오류 응답은 [3.1절](#31-오류-본문)의 RFC 9457 problem이다.
- 오류 코드 구분: HTTP 응답 코드 `llm_auth_required`(503)는 job이 시작되기 전에 인증이 없을 때다. job 오류 `llm_auth`는 실행 중 인증이 없거나 만료됐을 때다. HTTP 응답 코드 `revision_conflict`(409)는 요청의 base_revision이 head와 다를 때다. job 오류 `stale_revision`은 job이 끝났는데 영상 head가 이미 바뀌어 결과를 적용하지 않고 버릴 때다.
- 202 응답 본문은 `Job`이다. client는 `GET /jobs/{id}`를 보이는 탭에서 1초, 숨은 탭에서 5초 간격으로 조회한다. 기술 선택: SSE와 WebSocket을 쓰지 않는다. 이유: 인증·origin 검사 경로를 하나로 유지한다.
- 목록 응답은 `{items, next_cursor}` 봉투다. 요청은 `?cursor=&limit=`(최대 50)을 받는다. `next_cursor`는 불투명 문자열이고 client가 해석하지 않으며 마지막 쪽에서는 `null`이다.

### 3.1 오류 본문

- 오류 응답의 media type은 `application/problem+json`이고 본문은 `api.schema.json#/$defs/Problem`이다. [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details를 따른다.
- 표준 멤버는 `type`, `title`, `status`, `detail`, `instance`다. `status`는 HTTP 응답 코드와 같은 정수이고 `instance`는 요청 경로다. `title`은 code별 고정 요약이고 `detail`은 그 발생을 설명하는 문자열이다.
- `type`은 `https://app.invalid/problems/<code>`다. `.invalid`는 [RFC 2606](https://www.rfc-editor.org/rfc/rfc2606)이 예약한 이름이라 이 주소에 실제 문서를 두지 않는다.
- 확장 멤버는 `code`, `message_key`, `retryable`, `errors`다. `code`는 앱 오류 코드이고 `message_key`는 화면 문구 key이며 `retryable`은 같은 요청을 다시 보낼 수 있는지다. 화면 문구는 `message_key`로 frontend locale에서 찾는다.
- `errors`는 의미 검사 실패 목록이고 각 item의 `code`는 [1.3절](#13-의미-검사)의 코드다.
- 문맥 값은 확장 멤버로 돌려준다: `current_revision`(409 `revision_conflict`), `job_id`(409 `job_running`), `found`와 `supported`(422 `unsupported_version`).

## 4. HTTP API 목록

요청과 응답 본문 이름은 `api.schema.json`의 `$defs`다. 「키」는 Idempotency-Key 필요 여부다.

| 메서드와 경로 | 요청 | 성공 | 주요 오류 | 키 |
|---|---|---|---|---|
| GET `/health` | 없음 | 200 `{version, profile, deployment}` | 없음 | 아니오 |
| POST `/session/pair` | `PairRequest` | 200 `PairResponse`와 세션 cookie | 401 `pair_invalid`, 429 `rate_limited` | 아니오 |
| GET `/runtime` | 없음 | 200 `RuntimeStatus`(`brand` 필드에 표시 이름 포함) | 없음 | 아니오 |
| POST `/runtime/prepare` | 없음 | 202 Job `runtime_prepare` | 409 `job_running` | 예 |
| PUT `/credentials/llm` | `ApiKeyRequest` | 204 | 403 `loopback_only`, 400 `validation_failed` | 아니오 |
| GET `/credentials/llm` | 없음 | 200 `{configured}` | 없음 | 아니오 |
| DELETE `/credentials/llm` | 없음 | 204 | 403 `loopback_only` | 아니오 |
| GET `/catalog/{kind}` | `?video_id=&q=&cursor=&limit=` | 200 `{items: CatalogItem[], next_cursor}` | 404 `not_found` | 아니오 |
| GET `/catalog/{kind}/{id}` | 없음 | 200 manifest | 404 `not_found` | 아니오 |
| GET `/catalog/{kind}/{id}/media/{name}` | 없음 | 200 썸네일 PNG 또는 샘플 WAV | 404 | 아니오 |
| POST `/projects` | `CreateProjectRequest` | 201 Project | 400 | 예 |
| GET `/projects` | `?cursor=&limit=` | 200 `{items: Project 요약[], next_cursor}` | 없음 | 아니오 |
| GET `/projects/{pid}` | 없음 | 200 Project | 404 | 아니오 |
| DELETE `/projects/{pid}` | 없음 | 204 | 404, 409 `job_running` | 아니오 |
| POST `/projects/{pid}/videos` | `CreateVideoRequest` | 201 Video revision 1 | 404, 422 `unknown_catalog_id` | 예 |
| GET `/videos/{vid}` | 없음 | 200 `VideoView` | 404 | 아니오 |
| GET `/videos/{vid}/revisions` | `?cursor=&limit=` | 200 `{items: RevisionInfo[], next_cursor}`, `RevisionInfo`는 `{revision, created_at, created_by, change_id}` | 404 | 아니오 |
| GET `/videos/{vid}/revisions/{n}` | 없음 | 200 Video | 404 | 아니오 |
| POST `/videos/{vid}/draft` | `DraftRequest` | 202 Job `draft` | 409 `revision_conflict`, 503 `llm_auth_required` | 예 |
| POST `/videos/{vid}/script` | `BaseRevision` | 202 Job `script` | 409 | 예 |
| POST `/videos/{vid}/script/confirm` | `BaseRevision` | 200 Video | 409 `script_missing`, 409 `revision_conflict` | 예 |
| POST `/videos/{vid}/previews` | `BaseRevision`와 선택 `scene_ids` | 202 Job `preview` | 409 `script_not_confirmed` | 예 |
| POST `/videos/{vid}/scenes/confirm` | `BaseRevision` | 200 Video | 409 `script_not_confirmed`, 409 `scene_data_missing` | 예 |
| POST `/videos/{vid}/changes` | `ChangeRequest` | 200 ChangePlan, 확인이 필요 없으면 적용된 상태 | 409, 422 `invalid_op`, 422 `invalid_combination` | 예 |
| POST `/videos/{vid}/messages` | `MessageRequest` | 202 Job `chat` | 409 | 예 |
| GET `/changes/{cid}` | 없음 | 200 ChangePlan | 404 | 아니오 |
| POST `/changes/{cid}/preview` | 없음 | 202 Job `preview` (제안 상태의 정지 화면) | 409 `change_stale` | 예 |
| POST `/changes/{cid}/apply` | `BaseRevision` | 200 Video (이미 적용된 계획은 그 `applied_revision`의 Video) | 409 `revision_conflict`, 409 `change_stale` | 예 |
| POST `/changes/{cid}/reject` | 없음 | 200 ChangePlan | 409 `change_stale` | 예 |
| POST `/videos/{vid}/undo` | `BaseRevision` | 200 Video | 409 `nothing_to_undo` | 예 |
| POST `/videos/{vid}/precheck` | `BaseRevision` | 202 Job `precheck` | 409 `scenes_not_confirmed` | 예 |
| POST `/videos/{vid}/generate` | `BaseRevision` | 202 Job `generate` | 409 `scenes_not_confirmed`, 503 `runtime_not_ready` | 예 |
| POST `/videos/{vid}/references` | multipart `file`, `base_revision` | 202 Job `reference` | 413 `payload_too_large`, 415 `unsupported_media` | 예 |
| POST `/videos/{vid}/references/link` | `LinkRequest` | 202 Job `reference` | 403 `link_disabled`, 422 `url_not_allowed` | 예 |
| POST `/styles` | `StyleRequest` | 202 Job `style` | 409, 503 | 예 |
| POST `/templates` | `TemplateRequest` | 202 Job `template` | 409, 503 | 예 |
| POST `/bgm/code` | `BgmCodeRequest` | 202 Job `bgm_code` | 503 | 예 |
| POST `/bgm/uploads` | multipart `file`, `project_id` | 202 Job `bgm_upload` | 413 `payload_too_large`, 415 `unsupported_media` | 예 |
| GET `/bgm/{id}/audio` | 없음 | 200 WAV | 404 | 아니오 |
| POST `/projects/{pid}/presets` | `PresetRequest` | 201 Preset | 404 | 예 |
| GET `/projects/{pid}/presets` | `?cursor=&limit=` | 200 `{items: Preset[], next_cursor}` | 404 | 아니오 |
| GET `/jobs` | `?video_id=&state=&cursor=&limit=` | 200 `{items: Job[], next_cursor}` | 없음 | 아니오 |
| GET `/jobs/{jid}` | `If-None-Match` | 200 Job 또는 304 | 404 | 아니오 |
| POST `/jobs/{jid}/cancel` | 없음 | 202 Job `cancelling` 또는 200 Job `cancelled` | 409 `job_terminal` | 아니오 |
| POST `/jobs/{jid}/retry` | 없음 | 202 Job | 409 `job_not_retryable` | 예 |
| GET `/artifacts/{aid}` | `Range` 지원 | 200 또는 206 | 404 | 아니오 |
| GET `/videos/{vid}/download/{kind}` | kind는 `mp4`, `srt` | 200 attachment | 409 `not_built` | 아니오 |
| POST `/videos/{vid}/activity` | `ActivityRequest` | 204 | 400 | 아니오 |
| GET `/videos/{vid}/metrics` | 없음 | 200 `Metrics` | 404 | 아니오 |

### 4.1 단계 gate와 변경 적용

- `stage`는 draft, script_confirmed, scenes_confirmed 순서로만 앞으로 간다. 이는 생성 확인 gate이며 UI의 단계 이름 목록과 독립적이다. UI 단계 이름을 core enum으로 고정하지 않는다.
- UI 단계와의 대응: 대본 단계의 확인이 `script_confirmed`를, 편집 단계에서 영상 만들기를 시작하는 장면 확인이 `scenes_confirmed`를 세운다. 컨셉 확인은 이 gate에 값을 더하지 않는다([SPEC 2](SPEC.md#2-흐름)).
- `script` job이 대본 전체를 새로 쓰면 적용된 revision의 stage는 draft로 돌아간다.
- preview는 stage가 script_confirmed 이상일 때만 실행한다. 그 전 preview 호출 수는 0이어야 한다.
- generate는 stage가 scenes_confirmed일 때만 실행한다.
- `ChangePlan` 적용은 그 범위의 사용자 확인이다. 적용 뒤 stage는 유지된다.
- `requires_confirmation`이 false인 계획은 `POST /changes`에서 바로 적용하고 `applied_revision`을 채운다. UI는 되돌리기를 보인다.
- 확인이 필요한 조건은 대본 재작성, 여러 장면 변경, lock 변경, 사용자 값 덮어쓰기, TTS나 렌더 재실행이다.
- `draft` job은 base_revision이 아직 head면 결과를 바로 적용한다. head가 바뀌었으면 계획을 `proposed`로 남긴다.
- head가 바뀐 뒤의 `proposed` 계획은 `stale`이 된다. 적용 요청은 409 `change_stale`이다.
- 이미 `applied`인 계획의 적용은 `base_revision` 검사보다 먼저 200과 그 `applied_revision`의 Video를 돌려준다. 새 revision을 만들지 않고, 응답을 잃은 client의 재시도가 성공한다. `rejected` 계획의 적용은 409다.
- 앞뒤 장면의 옛 표현은 `stale_wording_in_neighbor` 경고만 남긴다. 자동으로 고치지 않는다.
- undo는 직전 revision의 원본을 새 revision으로 쓴다. 이전 결과는 같은 cache key로 다시 연결된다.
- `script` job은 대본이 없으면 결과를 바로 적용한다. 대본이 있으면 `script_rewrite` 확인이 필요한 계획을 만든다.
- 장면 하나 다시 만들기는 `target.scene_id`가 있는 `messages` 요청이다. text가 비어 있으면 그 장면만 새로 쓴다. 결과 계획은 그 장면만 바꾼다.
- style, template, bgm job의 결과는 package나 entry를 만들고, 영상에 적용하는 계획을 따로 만든다. 그림체 적용 계획은 `rebuild_render` 확인을 요구한다.

## 5. Job

상태 전이·queue·복구 세부는 [열린 질문](#저장과-job-구현)의 제안이다.

## 6. 저장 경로

### 6.1 root

이름 값의 원본은 `core/config/brand.yaml`이다. `display_name_ko`, `display_name_en`, `repository`, `app_id`를 갖는다. 이름은 팀과 논의해 바꿀 수 있고 저장소 rename과 설정을 함께 갱신한다. 코드·화면·설치기·문서는 이 파일에서 읽으며 frontend는 `GET /api/v1/runtime`의 `brand`를 받는다. `scripts/check_brand.py`가 이름 하드코딩을 검사한다. 예외는 `LICENSE`, `.git/`, 두 README뿐이다. Python package 이름은 `core`, frontend package 이름은 `frontend`다. 설치기 템플릿도 설정에서 생성한다. `app_id` 자리표시는 짧은 ASCII `app`이다. 앱 ID를 정식 배포 뒤 바꾸면 저장 폴더 migration이 필요하며 첫 배포 전에는 필요 없다. schema `$id`는 `https://app.invalid/schemas/<file>`다.

OS별 경로·파일 배치·보존 세부는 [열린 질문](#저장-경로와-보존)의 제안이다. 환경변수 `APP_DATA_DIR`, `APP_CACHE_DIR`, `APP_MODEL_DIR`, `APP_RUNTIME_DIR`로 격리한다.

## 7. 로그

- 형식은 JSON lines다. 위치는 `DATA_DIR/log/app.log`다. 5MB 회전, 3개 보관이다.
- 기록 필드: `ts`, `level`, `event`, `job_id`, `attempt`, `kind`, `stage`, `project_id`, `video_id`, `scene_id`, `error_code`, `http_status`, `provider`, `model`, `effort`, `input_tokens`, `output_tokens`, `cache_hit`, `duration_ms`(monotonic), `retries`.
- 기록하지 않는 것: prompt, 대본, 화면 글, 말할 글, 재료, 대화 문장, 참고 URL과 파일명, 프레임, 전사, LLM 원본 응답, provider 오류 본문, API key, Authorization과 cookie와 CSRF 값, pairing code, CLI stdout, 환경변수 dump, 절대 home 경로.
- 경로가 필요하면 root 이름과 상대 경로만 쓴다.
- 생성 코드의 traceback은 LLM 수정 요청에만 쓰고 로그에 쓰지 않는다.
- debug 수준도 같은 금지 목록을 따른다.

## 8. Cache key와 변경 범위

- 계산은 `core/app/services/pipeline/cache_keys.py` 한 곳에서 한다.
- key는 canonical JSON(UTF-8, key 정렬, 공백 없음, 숫자는 정수만, float 금지)의 SHA-256이다.
- 시간은 정수 ms다. dB 눈금 값(gain, ducking, 음량 목표, true peak)은 dB의 10배 정수로 저장하고 필드 이름에 `_x10`을 붙인다. 예: -3.5 dB는 `gain_db_x10: -35`이고 -16 LUFS는 `loudness_lufs_x10: -160`이다. 단위가 분명하지 않은 `speed`는 [숫자 형식](#숫자-형식)에 둔다.
- 각 key는 `kind`와 `api_version`을 포함한다.

| artifact | 넣는 입력 | 넣지 않는 입력 |
|---|---|---|
| `tts_wav` | speech_text, language, voice PinnedRef, engine runtime digest, speed(단위 미정), seed | display_text, 순서, BGM |
| `timing_json` | 줄별 tts digest, speech_text, display_text, language, 요청 caption mode, aligner runtime digest | 색, 글꼴, BGM |
| `part_png` | style PinnedRef, CharacterSpec, expression, pose, canvas, seed, sandbox runtime digest | 장면 글 |
| `layer_png` | template PinnedRef, 장면 visual, 장면 lines의 display_text, regions, canvas, 입력 part digest, seed | BGM, 순서 |
| `still_png` | 장면 visual과 lines, resolved theme, part digest, layer digest, font digest, caption 설정, layout, progress 문구, 해상도 | BGM, 순서, 다른 장면 |
| `clip_mp4` | still 입력 전체, timing digest, motion, fps, renderer revision | BGM, 순서, 다른 장면 |
| `mix_wav` | 순서 있는 timing digest와 tts digest, BGM entry digest, `gain_db_x10`, `ducking_db_x10`, SFX digest와 시점, 음량 목표 `loudness_lufs_x10` | 영상 화면 |
| `final_mp4` | 순서 있는 clip digest, mix digest, encoder 설정 | UI 상태 |
| `srt` | 순서 있는 timing digest, display_text | BGM |

- 진행 표시 문구는 장면 안의 beat 기준이다. 순서만 바뀌면 clip key는 그대로다.
- 결과: 화면 글만 바꾸면 TTS는 재사용한다. 순서만 바꾸면 final만 다시 만든다. BGM만 바꾸면 mix와 final만 다시 만든다. 말할 글 변경은 그 줄의 TTS만 무효화한다.
- `ChangePlan.effects`는 변경 전후 key 비교로 계산한다. 장면을 직접 나열하지 않는다.

## 9. Sandbox

생성 drawing code, 생성 template code, code BGM은 같은 runner에서만 실행한다. host Python에서 import하거나 exec하지 않는다. native fallback은 없다.

### 9.1 runner

- 위치는 `core/app/tools/sandbox/`다. 고정 Deno 진입 파일과 Python bootstrap이 있다.
- runtime은 Deno 2.9.8과 Pyodide 314.0.7이다. Pyodide Pillow wheel만 허용한다. 버전과 파일 SHA-256은 `core/config/runtime.lock.json`에 있다.
- Deno 실행 flag는 `--no-prompt`, `--no-config`, `--cached-only`, 고정 runtime 폴더만 허용하는 `--allow-read`, 그 밖의 write, net, env, run, ffi, sys, import 금지다. 정확한 flag 집합은 양 OS probe 결과로 고정한다.
- bootstrap 단계는 고정 runtime 폴더에서 Pyodide와 허용 wheel을 읽는다.
- bootstrap이 끝나면 read 권한을 회수한다. 회수와 권한 상태 검사가 성공하기 전에는 stdin을 읽지 않는다.
- 환경변수는 비운다. CWD는 비어 있는 전용 폴더다. Deno cache도 전용 폴더다. host filesystem mount는 없다.
- Python 쪽 import hook은 허용 목록(`math`, `random`, `struct`, `array`, `io`, `wave`, `colorsys`, `PIL`)만 연다. 이 hook은 보안 경계가 아니고 계약 표시다. 경계는 Deno 권한 회수와 부모 감독이다.

### 9.2 입출력

- 요청과 응답은 `sandbox-io.schema.json`이다. runner 프로토콜 버전은 저장 문서의 `schema_version`과 별개인 `protocol`(현재 1)이다. 요청 JSON 하나를 stdin에 쓰고 닫는다. runner는 응답 JSON 한 줄을 stdout에 쓴다.
- 진입 함수는 kind별로 고정이다.
  - `style_parts`: `build_assets(spec: dict, character: dict, canvas: dict, seed: int) -> dict[str, PIL.Image]`
  - `template_layer`: `render_layer(scene: dict, regions: dict, canvas: dict, parts: dict[str, PIL.Image], seed: int) -> (PIL.Image, dict)`
  - `bgm_loop`: `render_loop(params: dict, seed: int) -> bytes`이고 반환값은 WAV bytes다.
- 입력은 위 kind별 진입 함수에 필요한 인자로 한정하고 부모가 검증한다. API key, home 경로, 프로젝트 전체, 다른 영상은 보내지 않는다.
- 생성 코드는 부품과 layer PNG만 만든다. 프레임 위치, 페이드, 자막은 host Pillow가 합성한다.

### 9.3 부모 감독과 한도

기술 시작값이다. probe 실측 뒤 `core/config/app.yaml`의 `sandbox`에서 고친다.

| 항목 | 값 |
|---|---|
| wall time | style_parts 60초, template_layer 장면당 20초, bgm_loop 30초 |
| 메모리 | process tree 1GiB. Windows는 Job Object, Linux는 위임된 cgroup v2가 있으면 적용 |
| stdin | 12MiB |
| stdout | 48MiB, 한 줄 |
| stderr | 64KiB, 넘으면 버림 |
| 파일 수 | 64 |
| PNG | 한 변 최대 1920, 파일 최대 8MiB |
| WAV | mono PCM16 44.1kHz, 최대 16초, 최대 1.5MiB |

- Linux에서 cgroup을 쓸 수 없으면 timeout과 출력 상한만 적용한다. 이때 hard memory cap 미확인을 결과와 문서에 적는다. RSS 조회만으로 hard cap이라고 쓰지 않는다.
- 한도를 넘으면 부모가 process tree를 종료하고 `sandbox_timeout`, `sandbox_memory`, `sandbox_output_invalid` 중 하나로 실패시킨다.

### 9.4 출력 검증기

- PNG 검증기와 WAV 검증기는 별도 모듈이다.
- PNG: signature, IHDR의 폭과 높이를 decode 전에 검사한다. Pillow decode는 픽셀 상한을 건다. RGBA로 다시 encode해 부가 chunk를 버린다.
- WAV: RIFF와 WAVE header, fmt chunk의 PCM, channel 1, 44100Hz, 16bit, data 크기와 실제 frame 수, 파일 크기, 허용하지 않은 chunk를 검사한다. 최대 길이를 넘으면 거절한다. peak와 loudness를 측정해 manifest에 10배 정수로 쓴다.
- runner가 보낸 「검증 통과」 같은 필드는 믿지 않는다.

### 9.5 worker 수명과 cache

- template_layer worker는 같은 job 안의 같은 `video revision + template digest`에서만 재사용한다.
- 다른 영상, 코드 변경, 취소, 오류 뒤에는 worker를 폐기한다. 전역 warm pool은 없다.
- 결과 cache key는 code digest, runtime digest, kind, canonical input, seed다. hit면 sandbox를 실행하지 않는다.
- 실패하면 이전 package와 이전 BGM을 그대로 둔다.

### 9.6 거부 시험

양 OS에서 아래가 모두 거절되거나 부모가 종료해야 sandbox 안전 완료를 선언한다. 거부 시험이 실패하면 해당 기능을 중단한다. 고정 프로그램은 `core/tests/sandbox/programs/`에 둔다.

`js` bridge로 Deno API 접근, 파일 read, 파일 write, network, env 읽기, 하위 process 실행, FFI, 권한 재요청, 원격 import, 무한 계산, 메모리 급증, stdout flood, 잘못된 PNG, 잘못된 WAV header, 초과 길이 WAV, 이전 실행의 module이나 가상 FS 상태가 다음 실행에 남는지.

## 10. LLM adapter

### 10.1 인터페이스

```python
class LlmTask(StrEnum):
    draft = "draft"; script = "script"; split = "split"; scene_data = "scene_data"
    chat = "chat"; scene_rewrite = "scene_rewrite"; precheck = "precheck"
    reference_vision = "reference_vision"; style_code = "style_code"
    template_code = "template_code"; bgm_code = "bgm_code"

@dataclass(frozen=True)
class LlmPart:
    kind: Literal["text", "png"]
    text: str | None = None
    png: bytes | None = None          # reference frames only, max 8 per call

@dataclass(frozen=True)
class LlmRequest:
    task: LlmTask
    system: str                       # trusted app prompt
    parts: list[LlmPart]              # untrusted user and reference data, sent as data
    output_schema: dict | None        # JSON Schema generated from a Pydantic model
    max_output_tokens: int

@dataclass(frozen=True)
class LlmResult:
    text: str
    parsed: dict | None               # validated against output_schema by the adapter
    usage: Usage                      # same fields as job usage; unknown values are None

class LlmPort(Protocol):
    def complete(self, req: LlmRequest, *, cancel: CancelToken, deadline: float) -> LlmResult: ...
    def auth_state(self) -> Literal["ok", "missing", "expired", "unknown"]: ...
```

- 구현은 `core/app/llm/providers/<id>/adapter.py`다. provider SDK는 이 폴더 밖에서 import하지 않는다.
- `fixture` adapter의 녹화 응답 계약은 [열린 질문](#llm-routing)의 제안이다.
- `anthropic_api`는 공식 SDK를 쓴다. profile 기본값은 [ADR 0003](decisions/0003-separate-llm-providers-and-routing.md)을 따른다.
- `openai_compat`는 표준 OpenAI-compatible Chat Completions API로 endpoint를 호출한다. `base_url`과 model 이름을 설정한다. key가 필요한 endpoint는 keyring 또는 env에서 읽는다. key가 필요 없는 endpoint도 지원한다.
- `openai_compat`는 PNG를 OpenAI `image_url` content part로 보낸다. endpoint가 이미지를 거절하면 `reference_vision`은 `llm_refused`로 실패한다.
- `claude_cli`는 수정하지 않은 공식 CLI를 비대화 모드로 실행한다. profile 범위는 [ADR 0003](decisions/0003-separate-llm-providers-and-routing.md)을 따른다.
- endpoint 인증은 설정된 key만 사용한다. 기여자는 각자 자기 endpoint, 공식 CLI 또는 API key를 쓴다. 한 사람의 endpoint를 공유하지 않는다.

### 10.2 routing

확정된 상위 모델은 [SPEC 9.2](SPEC.md#92-모델과-출력), 미확정 세부 routing은 [열린 질문](#llm-routing)을 따른다.

### 10.3 실패, 시간 초과, 느림

| 오류 코드 | 원인 | adapter 재시도 | 사용자에게 |
|---|---|---|---|
| `llm_auth` | 인증 없음, 만료, CLI 로그아웃 | 없음 | profile에 맞는 인증 안내 |
| `llm_quota` | provider 사용 한도 | 없음 | 한도 안내, 성공 결과 보존 |
| `llm_rate_limited` | 429 | `Retry-After`를 따르고 최대 2회. 대기 중 취소 확인 | 대기 표시 |
| `llm_timeout` | 호출 timeout | 1회 | 재시도 버튼 |
| `llm_connection` | 연결 실패, 5xx | 지수 backoff 최대 2회 | 연결 필요 안내 |
| `llm_invalid_output` | schema 불일치 | 검증 오류를 붙여 1회 수정 요청 | 실패 표시 |
| `llm_refused` | 거절 | 없음 | 할 수 있는 부분과 못 하는 부분 표시 |

- 전체 job deadline은 5.2절을 따른다. deadline이 지나면 `deadline_exceeded`다.
- model, provider, effort를 조용히 바꾸지 않는다.
- 느린 응답은 `progress.waiting_on = "llm"`으로만 보인다. 남은 시간을 추정해 보이지 않는다.

### 10.4 보안 규칙

- 외부 LLM 전송 목록의 원본: 재료 글, 대본, 대화 문장(chat text), 참고 영상에서 추출한 프레임과 받아쓴 대사뿐이다. 최초 안내는 [SPEC 8b](SPEC.md#8b-참고-영상-자동-분석-reference-analysis)를 따른다.
- 참고 자료와 사용자 글은 데이터 part로만 보낸다. system prompt나 설정 파일에 넣지 않는다.
- LLM 출력은 typed patch와 코드 문자열로만 받는다. 서버가 허용 필드, scene ID, base revision, lock, catalog ID를 다시 검사한다.
- LLM이 URL, 실행 명령, dependency, host 경로를 등록하지 못한다.
- CLI adapter는 앱 전용 빈 CWD에서 실행한다. 사용자와 프로젝트 settings를 불러오지 않는다. 내장 tools, MCP, hooks, plugins를 끈다. 정확한 flag는 실제 설치 버전에서 확인한 값만 쓴다. 권한 우회 flag는 쓰지 않는다.
- CLI prompt는 stdin으로 보낸다. 환경변수는 allowlist다. API key 환경변수는 CLI process에 넘기지 않는다.
- 앱은 CLI credential 파일을 읽거나 복사하지 않는다.
- 배포판 API key는 backend만 가진다. Windows는 Credential Manager, Linux는 Secret Service를 쓴다. Linux에 keyring이 없으면 메모리에만 두고 그 사실을 알린다.

### 10.5 Prompt 문체와 작은 검토

prompt 파일 구조는 [ADR 0018](decisions/0018-store-prompts-as-files.md), 문체 구현안은 [열린 질문](#prompt-파일과-문체), 작성자의 수동 검토 절차는 [기여 안내](../CONTRIBUTING.md#prompt-검토)를 따른다.

## 11. TTS, 정렬, 전사

### 11.1 TTS provider

```python
@dataclass(frozen=True)
class TtsEngineInfo:
    engine_id: str
    runtime_digest: str               # model files + runtime wheels digest
    sample_rate: int
    languages: tuple[str, ...]

@dataclass(frozen=True)
class SynthResult:
    wav_path: Path                    # mono PCM16 temp file in the job folder
    duration_ms: int                  # measured from the WAV

class TtsPort(Protocol):
    def info(self) -> TtsEngineInfo: ...
    def ready(self) -> list[str]: ...                 # missing runtime item ids, empty when ready
    def synthesize(self, text: str, language: str, voice: VoiceManifest, *,
                   out_dir: Path, cancel: CancelToken) -> SynthResult: ...
    def close(self) -> None: ...
```

- 구현은 `core/app/tools/tts/<engine_id>/`다. 모델은 자식 worker process에서 한 번 load하고 job 동안 유지한다. 기술 선택: worker는 120초 idle 뒤 종료한다. 이유: 모델 reload 비용과 노트북 메모리를 함께 줄인다.
- 문장당 timeout은 30초와 예상 길이 10배 중 큰 값이다.
- 실패 코드는 `tts_not_ready`, `tts_failed`, `tts_timeout`이다. 무음이나 다른 엔진으로 대체하지 않는다.
- `fixed_wav` 엔진은 시험과 fixture profile 전용이다. 글자 수에 비례한 길이의 결정적 tone WAV를 만든다. 제품 catalog에는 노출하지 않는다.
- 네 후보 비교는 제품 코드 밖 `probes/tts/<candidate>/`에서 후보별 환경으로 한다. 공통 출력은 후보별 WAV, `result.json`(revision, OS, CPU, RAM, thread, cold_start_ms, rtf, peak_rss_bytes, 실패)이다.
- 제품에는 사용자가 듣고 고른 엔진 하나만 `tools/tts/<engine_id>/`로 넣는다.

### 11.2 정렬과 전사

```python
@dataclass(frozen=True)
class AlignResult:
    phrases: list[PhraseSpan] | None  # display_text char spans with ms
    failure: Literal["align_failed", "align_low_confidence", "align_missing_words", "align_unavailable"] | None

class AlignerPort(Protocol):
    def align(self, wav: Path, speech_text: str, display_text: str, language: str, *,
              cancel: CancelToken) -> AlignResult: ...

class TranscriberPort(Protocol):
    def transcribe(self, wav: Path, language: str | None, *, cancel: CancelToken) -> list[Segment]: ...
```

- 정렬은 알려진 대본의 forced alignment다. 기준선은 WhisperX다. 전사는 참고 영상용이고 별도 adapter다.
- 정렬이 실패하면 그 줄은 문장형 자막이다. `Timing.caption.fallback_reason`에 이유를 남긴다. 글자 비율로 나눈 가짜 시간은 만들지 않는다.
- 화면 글과 말할 글의 대응을 구절 단위로 기록한다. 대응이 끊기면 그 줄은 문장형이다.

## 12. Media (ffmpeg)

```python
class MediaPort(Protocol):
    def encode_frames(self, frames: Iterable[bytes], *, width: int, height: int, fps: int,
                      out: Path, cancel: CancelToken) -> MediaInfo: ...   # raw RGB24 via stdin, H.264 yuv420p
    def mix(self, plan: MixPlan, *, out: Path, cancel: CancelToken) -> MediaInfo: ...
    def mux_concat(self, clips: list[Path], audio: Path, *, out: Path, cancel: CancelToken) -> MediaInfo: ...
    def decode_audio(self, src: Path, *, out: Path, sample_rate: int, channels: int,
                     max_ms: int, cancel: CancelToken) -> MediaInfo: ...
    def extract_frames(self, src: Path, *, every_ms: int, max_frames: int, max_side: int,
                       out_dir: Path, cancel: CancelToken) -> list[Path]: ...
    def extract_audio(self, src: Path, *, out: Path, max_ms: int, cancel: CancelToken) -> MediaInfo: ...
    def probe(self, src: Path) -> MediaInfo: ...
```

- 구현은 `core/app/tools/media/`다. 실행 파일은 runtime lock의 절대 경로만 쓴다. PATH 검색은 하지 않는다.
- 인자는 배열이다. 사용자 문자열을 filtergraph, concat 목록, 경로에 넣지 않는다. concat 목록은 앱이 만든 artifact 경로만 쓴다.
- `-nostdin`, `-protocol_whitelist file,pipe`를 쓴다. 입력은 내려받거나 업로드된 로컬 파일뿐이다.
- 출력 규격은 1080×1920, 30fps, H.264 yuv420p, AAC 44.1kHz다. 정지 미리보기는 540×960 PNG다. 기술 선택: 미리보기는 최종의 절반 크기다. 이유: 같은 함수를 쓰면서 생성 시간을 줄인다.
- 자막 줄바꿈과 배치는 1080×1920 기준으로 실제 glyph 폭을 재서 한 번 계산한다. 미리보기는 같은 배치를 축소한다.
- 음량 목표는 -16 LUFS, true peak -1 dBTP다. 계약 값은 `loudness_lufs_x10: -160`과 `true_peak_dbtp_x10: -10`이다. BGM ducking은 sidechain으로 한다.
- 장면 clip은 무음 영상이다. 소리는 최종 mux에서 한 번 넣는다.

## 13. 설정, profile, 접근 제어

### 13.1 설정 파일

| 파일 | 내용 | 소유 |
|---|---|---|
| `core/config/app.yaml` | 앱 ID, profile 기본값, bind, 한도, job deadline, sandbox 한도, 업로드 한도 | 계약 |
| `core/config/models.yaml` | LLM routing | 계약 |
| `core/config/runtime.lock.json` | OS·CPU별 runtime 항목: 이름, 버전, URL, full revision, 파일 목록, bytes, SHA-256, 라이선스 | 계약 |

- `settings.py`가 위 파일과 환경변수를 읽어 typed `Settings`를 만든다. `bootstrap.py`만 이를 import한다.
- 환경변수: `APP_PROFILE`(fixture, dev, release), `APP_DEPLOYMENT`(local, hosted), `APP_PORT`, `APP_LAN`(1이면 LAN 모드), `APP_DATA_DIR`, `APP_CACHE_DIR`, `APP_MODEL_DIR`, `APP_RUNTIME_DIR`, `APP_LOG_LEVEL`.

| profile | LLM | TTS | 용도 |
|---|---|---|---|
| fixture | 녹화 응답 | `fixed_wav` | CI, UI e2e, 개발 |
| dev | `openai_compat` 기본, `claude_cli` 선택 가능 | 선택 엔진, 선택 전에는 `fixed_wav` | 개발 빌드 |
| release | `anthropic_api` | 선택 엔진 | 배포판 |

- 업로드 한도 시작값: 참고 영상 300MB와 3분, BGM 30MB와 10분, 재료 글 20,000자.
- hosted에서는 링크 다운로드 API가 403 `link_disabled`를 돌려준다.

### 13.2 접근 제어

- 기본 bind는 `127.0.0.1`이다. LAN 모드는 `APP_LAN=1`일 때만 사용자가 고른 interface에 bind한다.
- launcher가 실행마다 일회용 pairing code를 만든다. 컴퓨터의 브라우저는 `http://127.0.0.1:<port>/#pair=<code>`로 연다. LAN 모드에서 휴대폰은 사용자가 고른 interface의 LAN IP와 port로 접속하고 노트북 화면의 code로 pairing한다. fragment는 서버 로그와 Referer에 남지 않는다.
- SPA가 `POST /session/pair`로 code를 세션으로 바꾼다. 세션 cookie는 HttpOnly, SameSite=Strict다. 응답의 CSRF token은 메모리에만 둔다.
- 상태를 바꾸는 요청은 cookie, `X-CSRF-Token`, 정확한 `Origin`이 모두 맞아야 한다. `null` Origin은 거절한다.
- `Host`는 loopback 이름, 선택한 LAN IP, 설정한 이름만 허용한다.
- artifact, 미리보기, mp4 range 요청도 세션을 요구한다. data root를 static으로 mount하지 않는다. artifact ID만 경로로 해석한다.
- 휴대폰 pairing은 노트북 화면에 보인 일회용 code로 한다. code는 5분 뒤 만료된다.
- API key 입력과 변경은 loopback 요청에서만 받는다.
- LAN 모드에서는 debug traceback, reload, OpenAPI 문서 화면을 끈다.
- 응답 header: `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- 평문 LAN은 합성 자료 시험에만 쓴다. 이 제한을 안내 문서에 적는다.

## 14. 모듈 경계

import 방향은 모듈 구조 문서의 표를 따른다. 이 절은 각 모듈이 받는 것과 돌려주는 것이다. schema 타입 이름은 Pydantic 모델 이름이다.

### 14.1 ports (`core/app/ports.py`)

```python
class CancelToken(Protocol):
    def is_set(self) -> bool: ...
    def raise_if_set(self) -> None: ...                 # raises Cancelled
    def wait(self, seconds: float) -> bool: ...         # True when cancelled during the wait

class ProjectStore(Protocol):
    def new_id(self, prefix: str) -> str: ...
    def put_project(self, project: Project) -> None: ...
    def get_project(self, project_id: str) -> Project: ...
    def list_projects(self, owner_id: str) -> list[Project]: ...
    def delete_project(self, project_id: str) -> None: ...
    def append_revision(self, video: Video) -> Video: ...      # raises RevisionConflict unless revision == head + 1
    def get_video(self, video_id: str, revision: int | None = None) -> Video: ...
    def list_revisions(self, video_id: str) -> list[RevisionInfo]: ...
    def put_change(self, plan: ChangePlan) -> None: ...
    def get_change(self, change_id: str) -> ChangePlan: ...
    def put_preset(self, preset: Preset) -> None: ...
    def list_presets(self, project_id: str) -> list[Preset]: ...
    def add_activity(self, video_id: str, spans: list[ActivitySpan]) -> None: ...

class ArtifactStore(Protocol):
    def find(self, cache_key: str) -> Artifact | None: ...      # checks file existence and digest
    def publish(self, kind: ArtifactKind, cache_key: str, tmp: Path, media: dict,
                job_id: str | None) -> Artifact: ...            # verify, atomic rename, index
    def path(self, artifact_id: str) -> Path: ...
    def job_dir(self, job_id: str) -> Path: ...
    def hold(self, artifact_ids: list[str], holder: str) -> None: ...
    def release(self, holder: str) -> None: ...
    def sweep(self) -> int: ...                                  # removes unheld cache artifacts

class JobStore(Protocol):
    def create(self, job: Job) -> Job: ...
    def claim(self, queue: str) -> Job | None: ...              # atomic queued -> running
    def progress(self, job_id: str, attempt: int, progress: dict) -> None: ...
    def stage(self, job_id: str, attempt: int, record: dict) -> None: ...
    def checkpoint(self, job_id: str, attempt: int, cp: dict) -> None: ...
    def usage(self, job_id: str, attempt: int, usage: dict) -> None: ...
    def finish(self, job_id: str, attempt: int, state: str, result: dict | None,
               error: JobError | None, partial: bool) -> bool: ...   # False when stale
    def request_cancel(self, job_id: str) -> Job: ...
    def requeue(self, job_id: str) -> Job: ...
    def unfinished(self) -> list[Job]: ...

class CatalogPort(Protocol):
    def list(self, kind: str, *, video: Video | None = None) -> list[CatalogItem]: ...
    def get(self, kind: str, item_id: str, revision: str | None = None) -> BaseModel: ...  # raises UnknownCatalogId
    def pin(self, kind: str, item_id: str) -> PinnedRef: ...
    def package_dir(self, kind: str, ref: PinnedRef) -> Path: ...
    def register_generated(self, kind: str, staged_dir: Path) -> PinnedRef: ...   # validates, moves to DATA_DIR/s/

class PartsBuilder(Protocol):     # builtin style module or sandbox-backed generated style
    def build_parts(self, style: PinnedRef, character: CharacterSpec | None, expression_id: str,
                    pose_id: str, seed: int, *, cancel: CancelToken) -> dict[str, bytes]: ...   # PNG bytes

class LayerDrawer(Protocol):      # builtin template module or sandbox-backed generated template
    def draw_layer(self, template: PinnedRef, scene: Scene, canvas: tuple[int, int],
                   parts: dict[str, bytes], seed: int, *, cancel: CancelToken) -> tuple[bytes | None, dict]: ...

class SandboxPort(Protocol):
    def run(self, request: SandboxRequest, *, cancel: CancelToken) -> ValidatedOutput: ...
    def runtime_digest(self) -> str: ...

class DownloaderPort(Protocol):
    def fetch(self, url: str, *, out_dir: Path, max_bytes: int, max_ms: int,
              cancel: CancelToken) -> Path: ...    # raises DownloadBlocked, UrlNotAllowed, TooLarge

# LlmPort: section 10. TtsPort, AlignerPort, TranscriberPort: section 11. MediaPort: section 12.
```

`ValidatedOutput`는 부모 검증기를 통과한 파일 bytes와 측정값이다. `SandboxRequest`는 `sandbox-io.schema.json#/$defs/Request`의 Pydantic 모델이다.

### 14.2 서비스

서비스는 생성자로 port를 받는다. FastAPI 객체를 받지 않는다. 형제 서비스를 import하지 않는다. 단계 연결은 pipeline만 한다.

```python
class ProjectService:          # services/project, ports: ProjectStore, CatalogPort
    def create_project(self, req: CreateProjectRequest) -> Project: ...
    def create_video(self, project_id: str, req: CreateVideoRequest) -> Video: ...
    def view(self, video_id: str) -> Video: ...
    def apply_ops(self, video: Video, ops: list[Op], origin_default: Origin) -> Video: ...   # pure, no store write
    def validate(self, video: Video) -> list[Issue]: ...                                     # section 1.3
    def commit(self, plan: ChangePlan, base_revision: int) -> Video: ...
    def undo(self, video_id: str, base_revision: int) -> Video: ...
    def confirm_script(self, video_id: str, base_revision: int) -> Video: ...
    def confirm_scenes(self, video_id: str, base_revision: int) -> Video: ...
    def pick_varied(self, project: Project, previous: list[Video], seed: int) -> Settings: ...
    def save_preset(self, project_id: str, req: PresetRequest) -> Preset: ...

class StoryService:            # services/story, ports: LlmPort, CatalogPort
    def draft(self, video: Video, message: str, card_id: str | None, *, ctx: JobContext) -> list[Op]: ...
    def write_script(self, video: Video, *, ctx: JobContext) -> list[Op]: ...       # script + split
    def scene_data(self, video: Video, scene_ids: list[str], *, ctx: JobContext) -> list[Op]: ...
    def interpret(self, video: Video, text: str, target: Target, *, ctx: JobContext) -> Proposal: ...  # ops, notes, unsupported
    def rewrite_scene(self, video: Video, scene_id: str, instruction: str, *, ctx: JobContext) -> list[Op]: ...
    def precheck(self, video: Video, *, ctx: JobContext) -> PrecheckReport: ...

class ReferenceService:        # services/reference, ports: DownloaderPort, MediaPort, TranscriberPort, LlmPort
    def ingest(self, upload: Path | None, url: str | None, *, ctx: JobContext) -> Path: ...
    def analyze(self, source: Path, video: Video, *, ctx: JobContext) -> ReferenceOutcome: ...  # ops with origin reference, summary, style hints

class RenderService:           # services/render, ports: MediaPort, ArtifactStore, CatalogPort
    def still(self, video: Video, scene_id: str, parts: dict[str, bytes], layer: bytes | None,
              timing: Timing | None, *, ctx: JobContext) -> Path: ...          # PNG 540x960
    def clip(self, video: Video, scene_id: str, parts: dict[str, bytes], layer: bytes | None,
             timing: Timing, *, ctx: JobContext) -> Path: ...                 # silent mp4

class VoiceService:            # services/voice, ports: TtsPort, AlignerPort
    def estimate_ms(self, line: Line, language: str) -> int: ...
    def synthesize(self, voice: VoiceManifest, language: str, line: Line, *, ctx: JobContext) -> Path: ...
    def timing(self, scene: Scene, caption_mode: str, wavs: dict[str, Path],
               *, ctx: JobContext) -> Timing: ...

class SoundService:            # services/sound, ports: MediaPort, CatalogPort
    def pick_bgm(self, settings: Settings, recent: list[str], seed: int) -> PinnedRef: ...
    def import_upload(self, src: Path, project_id: str, *, ctx: JobContext) -> BgmEntry: ...
    def mix(self, video: Video, timings: list[Timing], tts: dict[str, Path], *, ctx: JobContext) -> Path: ...

class AssembleService:         # services/assemble, ports: MediaPort
    def final(self, clips: list[Path], mix: Path, *, ctx: JobContext) -> Path: ...
    def srt(self, video: Video, timings: list[Timing]) -> str: ...

class TemplatesService:        # services/templates, ports: LlmPort, SandboxPort, CatalogPort
    def generate_style(self, req: StyleRequest, video: Video, hints: dict | None, *, ctx: JobContext) -> PinnedRef: ...
    def generate_template(self, req: TemplateRequest, video: Video, *, ctx: JobContext) -> PinnedRef: ...
    def generate_bgm(self, req: BgmCodeRequest, *, ctx: JobContext) -> PinnedRef: ...
    def parts_builder(self, style: PinnedRef) -> PartsBuilder: ...
    def layer_drawer(self, template: PinnedRef) -> LayerDrawer: ...

def run(job: Job, ctx: JobContext, services: Services) -> dict:   # services/pipeline/run.py, the run_job callable
    ...
def plan_change(video: Video, ops: list[Op], source: str, target: Target,
                services: Services) -> ChangePlan: ...           # services/pipeline/dependencies.py
def build_view(video: Video, services: Services) -> VideoBuild: ...
```

- `JobContext`는 jobs가 만든다. `cancel`, `deadline`, `job_dir`, `progress()`, `stage()` context manager, `checkpoint()`, `record_usage()`를 제공한다.
- 서비스는 결과 파일을 job 폴더에 쓴다. 공개와 index는 pipeline이 `ArtifactStore.publish`로 한다.
- 외부 실패는 adapter에서 `AppError(code)`로 바꾼다. 서비스는 provider 예외를 보지 않는다.

### 14.3 모듈별 소유 파일

| 모듈 | 소유 폴더 |
|---|---|
| 계약 | `schemas/`, `core/app/schemas/`, `core/app/ports.py`, `core/config/`, `fixtures/`, `core/tests/contracts/`, `core/tests/architecture/`, `frontend/src/shared/api/generated/`, `frontend/src/shared/ui/tokens.css`, lockfile, `core/pyproject.toml`, `frontend/package.json`, `.github/workflows/ci.yml`, `scripts/export_*.py`, `scripts/check_brand.py` |
| 앱 조립 | `core/app/main.py`, `core/app/bootstrap.py`, `core/app/settings.py`, `core/app/routers/`, `core/app/access/` |
| 상태 | `core/app/storage/`, `core/app/jobs.py` |
| 서비스 | `core/app/services/<name>/` |
| adapter | `core/app/llm/`, `core/app/tools/{process.py,media,sandbox,tts,align,asr,downloaders}/` |
| plugin | `core/app/plugins/{registry.py,art_styles,templates,voices,bgm,sfx,fonts}/`, `core/app/catalog/` |
| 설치 | `core/app/runtime/`, `packaging/`, `.github/workflows/release.yml` |
| frontend | `frontend/src/{app,features,shared/ui,shared/lib}/`, `frontend/src/shared/api/client.ts`, `frontend/tests/` |
| 디자인 부품 | `frontend/src/components/`, `frontend/src/gallery/`, `frontend/tests/gallery/`(디자인 작업만 변경한다) |

기술 선택: 기본 화면 틀도 `plugins/templates/`의 template manifest로 등록한다. 이유: 기본과 생성 화면 틀이 같은 catalog 계약을 쓴다. `core/app/plugins/templates/`는 화면 틀 데이터(manifest와 에셋)이고 `core/app/services/templates/`는 생성 서비스 코드다. 이름이 비슷하지만 다른 폴더다. 기술 선택: `core/app/tools/{media,align,asr}/`와 `core/app/access/`를 구조 tree에 추가한다. 이유: ffmpeg, 정렬, 전사, 접근 제어가 별도 교체·공격 경계다.

## 15. Fixtures

기술 선택: 계약 fixture는 저장소 root `fixtures/`에 둔다. 이유: core 시험과 frontend mock이 같은 파일을 읽는다. binary fixture는 commit하지 않는다. WAV와 PNG는 시험 시작 때 결정적으로 만든다.

| 경로 | 내용 |
|---|---|
| `fixtures/contracts/valid/project_min.json` | 최소 프로젝트 |
| `fixtures/contracts/valid/video_ko_just_three.json` | 한국어, 딱 3가지만, 장면 5개, 실제 픽셀 에셋 ID, stage scenes_confirmed |
| `fixtures/contracts/valid/video_en_its_like.json` | 영어, ○○로 치면, 장면 5개, 실제 에셋 ID |
| `fixtures/contracts/valid/video_ko_draft_no_visual.json` | 대본 확인 전, visual null |
| `fixtures/contracts/valid/scene_fixed_stage.json` | fixed_stage 장면, 진행자 |
| `fixtures/contracts/valid/scene_full_stage.json` | full_stage 장면, 장면 속 인물 |
| `fixtures/contracts/valid/scene_dialog_stage_typewriter.json` | dialog_stage, typewriter |
| `fixtures/contracts/valid/scene_generated_template.json` | 생성 template 시험 장면 |
| `fixtures/contracts/valid/scene_text_edge.json` | 긴 한글, 영문 식별자, 숫자, 괄호, 혼합 문자, display와 speech 차이 |
| `fixtures/contracts/valid/preset_min.json` | 프리셋 |
| `fixtures/contracts/valid/change_single_value.json` | 확인 없이 적용되는 값 하나 변경 |
| `fixtures/contracts/valid/change_scene_rewrite.json` | 장면 하나 재작성, 확인 필요 |
| `fixtures/contracts/valid/change_reorder.json` | 순서만 변경 |
| `fixtures/contracts/valid/job_<state>.json` | 상태 6개마다 하나 |
| `fixtures/contracts/valid/timing_sentence_fallback.json` | 정렬 실패 문장형 timing |
| `fixtures/contracts/valid/bgm_builtin.json`, `bgm_upload.json`, `bgm_code.json`, `sfx_pop.json` | BGM과 효과음 |
| `fixtures/contracts/valid/style_generated.json`, `template_generated.json`, `voice_fixed_wav.json` | 생성 package와 시험 목소리 |
| `fixtures/contracts/invalid/*.json`과 `expect.json` | 아래 목록. `expect.json`은 파일별 기대 오류 code다 |
| `fixtures/api/<operationId>.json` | endpoint별 요청과 응답 예시. frontend mock이 읽는다 |
| `fixtures/llm/<task>/<digest>.json` | fixture profile의 녹화 LLM 응답. 합성 주제만 쓴다 |
| `core/tests/sandbox/programs/*.py` | 9.6절 거부 시험과 정상 프로그램 |
| `core/tests/fixtures/media.py` | 결정적 tone WAV, 손상 WAV, 잘못된 PNG 생성 함수 |

실패 fixture 목록: `unknown_asset_id`, `unknown_card_id`, `duplicate_scene_order`, `order_scene_mismatch`, `duplicate_line_id`, `typewriter_fixed_stage`, `role_none_with_character`, `presenter_without_character`, `highlight_out_of_range`, `reveal_line_unknown`, `bad_digest`, `extra_field`, `schema_version_2`, `path_escape_asset`, `bgm_code_20s`, `voice_cloning_true`, `stale_base_revision_request`(API 요청 fixture).

- 정상 fixture는 실제 기본 plugin의 ID만 참조한다. 설명용 가짜 ID를 쓰지 않는다.
- fixture 화면 완주는 실제 생성 증거가 아니다. 실제 생성 증거는 dev나 release profile 실행 기록이다.
- 공개 PR 증거는 합성 주제와 합성 자료만 쓴다.

## 16. 구현과 검증

### 현재 검증 범위

- 현재 release 빌드에는 API key를 등록하지 않는다. `anthropic_api` 구현과 fake 응답 시험은 계속하되 실제 API 호출은 미실행으로 기록한다. fake·fixture 결과를 실호출 성공으로 보고하지 않는다.
- 선택 TTS, 렌더, 설치 시험은 실호출과 구분해 가능한 범위에서 계속한다.

### 16.1 원본과 runtime

- 기술 설계: frontend는 React 18, TypeScript 5.7, Vite 6, Tailwind 4다. 화면 부품은 shadcn/ui on Base UI다([ADR 0023](decisions/0023-build-components-on-shadcn-base-ui.md)). core는 Python 3.11, FastAPI, Pydantic v2, Poetry다.
- 기술 설계: 여럿 실행에 대비해 `owner_id`를 두고 한 명 실행은 고정값을 쓴다. 실행 형태의 제품 범위는 [SPEC 1](SPEC.md#1-범위와-실행-형태)을 따른다.
- 계약 구현은 stable scene·line ID, schema_version, base revision, style/template digest, origins, lock, artifact 참조를 Pydantic 원본과 OpenAPI로 만든다. 조사 예시 JSON은 실행 규격이 아니다. 한영 정상 fixture와 잘못된 ID·중복 순서·오래된 revision fixture를 둔다. API method·path·입출력·오류·중복·충돌과 TS 생성은 0~4절을 따른다.
- 재시작과 긴 대화 뒤에도 직접값, lock, 과거 영상이 바뀌지 않는지 시험한다.
- 저장과 job 세부는 아래 제안의 상태를 유지한다. 재시작 뒤 성공 결과와 마지막 저장 상태를 재사용하는 제품 수락은 [SPEC 기준 27](SPEC.md#106-복구와-품질-검수-2630)을 따른다.

### 16.2 그림과 timing

- 기술 설계: 정지 미리보기는 대본 확인 뒤 구도 검수용이다. TTS 전 길이는 예상값이다. 확정 음성 뒤 preview와 mp4는 같은 timing artifact를 읽는다. 글·font·style·revision 변경 뒤 오래된 preview를 완료로 표시하지 않는다.
- 한영 font 파일·digest·원본 라이선스를 동봉한다. 실제 glyph와 픽셀 폭으로 줄바꿈하며 OS 기본 font로 조용히 대체하지 않는다. 긴 한글·영문 식별자·숫자·괄호·혼합문자·누락 glyph·자모 분리·타자 효과 fixture를 시험한다.
- 코드 BGM은 9절 sandbox와 별도 WAV 검증기를 쓴다. host sound 서비스가 반복과 영상 길이를 처리한다. code/runtime digest·seed·설정으로 WAV를 재사용한다. 고정 WAV·잘못된 header·초과 길이·stdout flood·무한 계산·cache hit를 시험한다. BGM 교체 때 renderer 호출은 0이다.
- 업로드 BGM은 job 전용 ID로 저장하고 고정 decoder로 제한한 내부 오디오로 변환한다. 손상·초과 bytes·길이는 거절한다. 보존 기간은 아래 저장 제안을 따른다.

### 16.3 TTS와 참고 분석

- 기술 시험안: Qwen 비교는 `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`, `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`에서 시작한다. 후보별 환경에서 full revision·설정·OS·CPU·RAM·thread를 기록한다. Base checkpoint 클로닝 시험은 별도 실험이며 후보 비교 승인을 클로닝 UI 승인으로 확대하지 않는다.
- 기술 수락: cold start는 process 시작부터 합성 준비까지, RTF는 wall time/실제 WAV 길이, peak RAM은 자식 process 포함이다. 설치 실패와 청취 부적합도 남긴다. 전부 실패하면 무음·대체 엔진 대신 TTS 미확정 blocker로 보고한다. 최종 한국어·영어 청취를 수행한다.
- 기술 설계: 전사와 알려진 대본의 forced alignment는 별도 adapter다. WhisperX는 정렬 기준선이며 가벼운 경로는 한영 시험 통과 때만 대체한다. 화면 글과 말할 글의 대응은 11.2절을 따른다.
- 기술 설계: 참고 화면은 ffmpeg 프레임으로, 소리는 별도 전사 adapter로 분석한다. 무음 비율·BGM 유무·길이·장면 수를 측정한다. 확정 분석값과 검증 artifact로 삭제·복구를 연결한다. 공급자 보관 정책과 실제 링크 성공은 검증 대기다. 링크 경계는 [SPEC 8b](SPEC.md#8b-참고-영상-자동-분석-reference-analysis)를 유지한다.

### 16.4 기록과 연결 상태

- job·attempt·stage·provider/model·effort·cache hit·usage·재생성 scene ID·monotonic 시작과 끝을 기록한다. 전체 wall time과 병렬 단계 시간을 구분한다. 로그 수집 범위는 7절을 따른다.
- 사용자 조작 시간은 초안 편집 시작부터 다음 행동까지 활성 구간이다. 대기와 비활성 탭은 분리한다. provider 사용량을 API 현금 비용으로 환산하지 않으며 미확인 비용은 0이 아닌 null이다.
- offline은 기존 프로젝트 열기·편집·결과 재생의 가능 범위를 표시한다. 로컬 모델 준비 여부에 따라 음성·렌더 가능 경로와 누락 모델을 정확히 알린다. LLM 생성·참고 분석은 연결이 필요하다. 전체 offline 앱이라고 설명하지 않는다.

### 16.5 기기 검증

- 결정: Playwright의 iPhone·Pixel profile과 Chromium·WebKit으로 390px 네 단계 완주·화면 캡처를 구현 변경마다 시험한다. 각자 Chrome DevTools 기기 모드로 직접 조작하고 Android Studio의 Chrome으로 키보드와 아래 입력창을 확인한다.
- 한계: 앞 두 경로는 실제 키보드·손가락 터치·iOS Safari를 재현하지 못한다. Playwright WebKit은 iOS Safari가 아니다. 마지막에 실기기로 한 번 시험한다. 같은 와이파이가 아니면 Tailscale이나 터널을 쓴다.

## 열린 질문

### 데이터 문서 배치

제안: 저장 위치는 [ADR 0007](decisions/0007-persist-storage-and-job-state.md)의 Proposed 범위다. schema 종류와 필드 계약은 본문을 따른다.

| 파일 | 정의 | 저장 위치 |
|---|---|---|
| `common.schema.json` | ID, digest, PinnedRef, Origin, License, Box 등 공통 정의 | 없음 |
| `settings.schema.json` | 제작 설정 `Settings`, 프리셋 설정 `PresetSettings` | project, video, preset 안 |
| `project.schema.json` | 프로젝트와 기본 설정 | `DATA_DIR/p/<project_id>/project.json` |
| `video.schema.json` | 영상 revision snapshot, `VideoBuild` 파생 view | `DATA_DIR/p/<pid>/v/<vid>/r/<revision>.json` |
| `script.schema.json` | 대본 metadata와 `Line` | video 안 |
| `scene.schema.json` | 장면 원본과 시각 데이터 | video 안 |
| `change.schema.json` | 변경 제안 `ChangePlan`과 `Op` | state.db `changes` |
| `preset.schema.json` | 프리셋 | state.db `presets` |
| `format-card.schema.json` | 포맷 카드, 이야기 틀 `StoryStructure` | `core/app/catalog/format_cards/<id>.json`, `core/app/catalog/story_structures/<id>.json` |
| `style-manifest.schema.json` | 그림체 package | 기본 `core/app/plugins/art_styles/<id>/`, 생성 `DATA_DIR/s/<digest16>/` |
| `template-manifest.schema.json` | 화면 틀 template | 기본 `core/app/plugins/templates/<id>/`, 생성 `DATA_DIR/s/<digest16>/` |
| `voice-manifest.schema.json` | 목소리 | `core/app/plugins/voices/<id>/` |
| `bgm-entry.schema.json` | BGM 내장·업로드·코드, `SfxEntry` | 내장 `core/app/plugins/bgm/<id>/`, 업로드 `DATA_DIR/p/<pid>/u/`, 코드 `DATA_DIR/s/<digest16>/`, 효과음 `core/app/plugins/sfx/<id>/` |
| `font-manifest.schema.json` | 자막 글꼴 | `core/app/plugins/fonts/<id>/` |
| `job.schema.json` | job과 오류 | state.db `jobs` |
| `artifact.schema.json` | artifact index와 `Timing` | state.db `artifacts`, 파일은 6절 |
| `sandbox-io.schema.json` | sandbox runner 입출력 | 저장하지 않음 |
| `api.schema.json` | RFC 9457 problem과 요청·응답 본문 | 저장하지 않음 |

- 열린 결정: 컨셉 확인 뒤 컨셉 값이 바뀌지 않는다는 규칙([SPEC 2](SPEC.md#2-흐름))을 저장 상태로 따로 둘지 정하지 않았다. 지금은 필드를 더하지 않고 4.1의 `stage`와 revision 값만 쓴다.

### 저장과 job 구현

제안: 아래 상태·queue·복구는 [ADR 0007](decisions/0007-persist-storage-and-job-state.md)에 따라 비구속적이다. 본문의 SQLite index와 불변 revision 참조도 이 제안의 승인을 뜻하지 않는다.

### 5.1 상태 전이

| 현재 | 사건 | 다음 |
|---|---|---|
| (없음) | 제출 | queued |
| queued | runner가 원자적으로 점유 (`UPDATE ... WHERE state='queued'`) | running |
| queued | 취소 | cancelled |
| running | 성공 | succeeded |
| running | 실패 | failed |
| running | 취소 요청 | cancelling |
| cancelling | 자식 process tree 종료 확인 | cancelled |
| failed, cancelled | 재시도 (`attempt < max_attempts`) | queued, attempt + 1 |
| running, cancelling | 앱 재시작 | 아래 5.3 |

- job 행은 terminal 상태가 되기 전에 지우지 않는다.
- 결과 기록은 `finish(job_id, attempt, ...)`가 `state='running' AND attempt=?` 조건으로만 성공한다. 취소 뒤나 이전 attempt의 늦은 결과는 버린다.
- checkpoint는 artifact를 검증하고 atomic rename으로 공개한 뒤에만 기록한다.

### 5.2 kind별 deadline과 실행 queue

기술 시작값이다. `core/config/app.yaml`의 `jobs`에서 바꾼다.

| kind | queue | deadline | 최대 attempt |
|---|---|---|---|
| draft, script, chat, precheck | light | 180초 | 3 |
| preview | heavy | 600초 | 3 |
| generate | heavy | 2400초 | 3 |
| reference | heavy | 900초 | 2 |
| style, template | heavy | 900초 | 2 |
| bgm_code | heavy | 300초 | 2 |
| bgm_upload | light | 120초 | 1 |
| runtime_prepare | heavy | 없음 | 3 |

- 기술 선택: light queue와 heavy queue가 각각 한 번에 job 하나를 실행한다. 이유: 노트북 메모리에서 무거운 모델을 동시에 올리지 않는다.
- TTS, 정렬, 전사 worker는 heavy queue 안에서 한 번에 하나만 살아 있다.

### 5.3 재시작 복구

1. 앱 시작 때 `running`과 `cancelling` job을 찾는다.
2. `cancelling`은 `cancelled`로 바꾼다.
3. `running`은 현재 attempt를 `interrupted`로 닫는다.
4. attempt가 남았고 kind가 재개 가능하면 queued로 되돌린다. 재개 가능 kind는 preview, generate, runtime_prepare, reference다.
5. 그 밖에는 failed와 `interrupted`로 닫는다. 사용자가 재시도한다.
6. 재개한 job은 checkpoint의 artifact 존재와 digest를 다시 검사한다. 통과한 것만 재사용한다.
7. `CACHE_DIR/j/`와 `CACHE_DIR/r/`에서 활성 job이 아닌 폴더를 지운다. 앱 소유 prefix와 job ID 형식이 맞는 폴더만 지운다. symlink는 따라가지 않는다.

### 5.4 부분 결과, 재시도, 취소

- generate는 장면 단위 checkpoint를 남긴다. 실패해도 성공한 장면 artifact는 index에 남는다. `partial`은 true다.
- 재시도는 같은 job ID의 새 attempt다. cache key가 같은 artifact를 다시 만들지 않는다.
- 사용자 재시도와 adapter 내부 재시도는 다르다. adapter 재시도는 10절과 11절을 따른다.
- 취소는 cancel token을 세우고 모든 자식 process tree를 종료한다. 429 대기 중에도 250ms 안에 취소를 확인한다.
- 이미 보낸 외부 LLM 요청의 과금 취소는 보장하지 않는다.
- 엔진, 목소리, 모델 변경과 재생성 범위 확대는 조용히 하지 않는다. 필요하면 job을 실패시키고 이유 코드를 남긴다.
- 실패한 job은 이전 성공 결과와 이전 BGM을 바꾸지 않는다.

### 저장 경로와 보존

제안: 다음은 OS별 사용자 경로와 파일 배치·보존안이다.

| root | Windows 기본값 | Linux 기본값 |
|---|---|---|
| `DATA_DIR` | `%LOCALAPPDATA%\<app_id>\data` | `$XDG_DATA_HOME/<app_id>`, 없으면 `~/.local/share/<app_id>` |
| `CACHE_DIR` | `%LOCALAPPDATA%\<app_id>\cache` | `$XDG_CACHE_HOME/<app_id>`, 없으면 `~/.cache/<app_id>` |
| `MODEL_DIR` | `DATA_DIR\models` | `DATA_DIR/models` |
| `RUNTIME_DIR` | 설치 폴더 `rt\` | 설치 폴더 `rt/` |
| 설치 폴더 | `%LOCALAPPDATA%\Programs\<app_id>\<version>\` | tarball을 푼 폴더 |

개발과 시험은 worktree 안 `.local/`을 쓴다. 환경변수 override는 [6.1절](#61-root)을 따른다.

### 6.2 배치

```text
DATA_DIR/
  state.db                      projects, videos, revisions index, changes, presets, jobs, artifacts, holds, idempotency, uploads, activity, catalog_user
  p/<project_id>/project.json
  p/<project_id>/v/<video_id>/r/<revision>.json
  p/<project_id>/u/<upload_id>.wav
  o/<video_id>/<artifact_id>.mp4 | .srt
  s/<digest16>/                 생성 style, template, code BGM package (immutable)
  models/<runtime_item>/<rev12>/
  rt-journal.json               기기별 설치 journal
  log/app.log                   회전 로그
CACHE_DIR/
  a/<2 hex>/<artifact_id>.<ext> 중간 artifact
  j/<job_id>/                   job 작업 폴더
  r/<job_id>/                   참고 영상 원본과 프레임, 분석 직후 삭제
```

- 파일은 임시 이름으로 쓰고 검증 뒤 같은 volume에서 atomic rename한다.
- 사용자 파일명과 원본 제목은 경로에 쓰지 않는다. 앱 ID만 쓴다.
- 경로 최대 길이 목표는 root 뒤 80자 이하다.

### 6.3 소유와 보존

| 경로 | 쓰는 모듈 | 삭제 규칙 |
|---|---|---|
| `state.db` | `storage` | migration 백업만 남긴다 |
| `p/` | `storage` (project 서비스 요청) | 프로젝트 삭제 때 해당 프로젝트만 지운다 |
| `p/<pid>/u/` | `storage` (sound 서비스 요청) | 프로젝트가 참조하는 동안 보존한다 |
| `o/` | `storage` (assemble 결과 공개) | 영상이나 프로젝트 삭제 때만 지운다 |
| `s/` | `plugins/registry` (templates 서비스 요청) | 참조하는 revision, 프리셋, catalog 항목이 없을 때만 지운다 |
| `models/` | `runtime` | uninstall 기본 보존 |
| `CACHE_DIR/a/` | `storage` | `sweep`이 hold 없는 항목만 지운다 |
| `CACHE_DIR/j/`, `r/` | `jobs`, reference 서비스 | job 종료 `finally`와 시작 복구에서 지운다 |

- hold 주체는 `rev:<video_id>:<revision>`, `undo:<video_id>`, `style:<digest>`, `preset:<preset_id>`다.
- 현재 revision과 직전 revision의 artifact는 hold로 보호한다.
- uninstall은 `DATA_DIR`과 `MODEL_DIR`을 기본 보존한다.
- 참고 원본 삭제의 제품 정책은 [SPEC 8b](SPEC.md#8b-참고-영상-자동-분석-reference-analysis)를 따른다. 기술 제안: 분석 job 종료 때 추출 프레임·전사 원문도 지우고 `ReferenceSummary`와 적용 설정값만 남긴다.

### LLM routing

제안: fixture adapter와 세부 routing·effort는 미확정이다. `fixture` adapter는 `fixtures/llm/<task>/<digest>.json` 녹화 응답을 돌려주며 없으면 `llm_invalid_output`으로 실패한다. fixture 성공을 실제 provider 성공으로 보고하지 않는다. 품질과 사용량을 같은 입력으로 비교하고 실제 provider 수락을 별도로 수행한다.

`core/config/models.yaml`이 task별 model, effort, timeout, 재시도를 정한다. profile별 값을 둔다.

```yaml
routes:
  draft:            {model: haiku,  effort: low,    timeout_s: 60,  retries: 2}
  script.numbered_three: {model: haiku, effort: low, timeout_s: 90, retries: 2}
  script.default:   {model: sonnet, effort: medium, timeout_s: 120, retries: 2}
  split:            {model: haiku,  effort: low,    timeout_s: 60,  retries: 2}
  scene_data:       {model: haiku,  effort: low,    timeout_s: 90,  retries: 2}
  chat:             {model: haiku,  effort: low,    timeout_s: 60,  retries: 2}
  scene_rewrite:    {model: sonnet, effort: medium, timeout_s: 90,  retries: 2}
  precheck:         {model: haiku,  effort: low,    timeout_s: 60,  retries: 1}
  reference_vision: {model: sonnet, effort: medium, timeout_s: 120, retries: 1}
  style_code:       {model: sonnet, effort: high,   timeout_s: 240, retries: 1}
  template_code:    {model: sonnet, effort: high,   timeout_s: 240, retries: 1}
  bgm_code:         {model: sonnet, effort: high,   timeout_s: 180, retries: 1}
models:
  haiku:  {anthropic_api: <Haiku 5.5 model id>,  claude_cli: <same alias>, openai_compat: <configured endpoint model id>}
  sonnet: {anthropic_api: <Sonnet 5.5 model id>, claude_cli: <same alias>, openai_compat: <configured endpoint model id>}
```

- 제안: 상위 모델 결정은 [SPEC 9.2](SPEC.md#92-모델과-출력)를 따른다. 단순 카드 대본·장면 나누기·장면 데이터는 Haiku 5.5, 나머지 카드 대본·새 템플릿은 상위 모델을 배정한다. 장면 하나 재작성과 생성 코드도 상위 모델로 시작한다.
- `anthropic_api`와 `claude_cli`의 실제 model ID는 LLM adapter 작업이 공식 문서에서 확인해 넣는다. `openai_compat`의 model ID는 alias마다 endpoint 설정으로 넣는다.
- 실행 때 실제 provider, model, effort를 job usage에 기록한다.
- 제안: Opus도 routing 후보로 둔다. 같은 작업을 더 적은 출력과 재시도로 끝내면 작업당 비용이 Sonnet보다 낮을 수 있고, 그림체 코드와 참고 프레임 같은 시각 작업은 상위 모델 추천이 있다. 같은 입력의 작업당 비용과 품질 비교 뒤 정한다.

- 제안: effort 출발값은 Sonnet 대본 medium·새 템플릿 high, Haiku 장면 나누기·장면 데이터 low, 참고 프레임 medium이다. [Anthropic effort](https://platform.claude.com/docs/en/build-with-claude/effort)를 출발점으로 같은 주제의 자체 평가를 거쳐 바꾸며 routing 설정에 모은다.

### 렌더 구현

- 제안: 모델 템플릿은 장면 데이터 입력·프레임 출력 규칙과 시험 장면 하나의 sandbox 렌더를 통과해야 저장한다.
- 제안: Python Pillow와 ffmpeg를 유지한다. SVG 컷아웃은 CairoSVG로 PNG로 미리 바꾼다. LGPLv3 배포 방식을 확인한다. 장면별 mp4를 조립하며 전환은 컷과 장면 안 페이드부터 시작한다. 정지 PNG 미리보기는 같은 렌더 함수로 만든다.
- 제안: 실행 형태는 deployment profile 설정 하나로 고르고 파일 저장·작업 실행·LLM 연결·사용자 구분만 인터페이스로 나눈다.
- 제안: LLM은 검수 에셋 ID만 고르고 목록 밖 ID는 렌더러가 거절한다. 변화 값의 선택 주체는 [SPEC 열린 질문](SPEC.md#고정과-그림체)의 LLM안과 1.2절의 seed 함수안을 비교해 정한다.

### 숫자 형식

- 열린 질문: TTS 속도 배율 `speed`는 `tts_wav` key 입력인데 dB나 ms처럼 단위가 분명하지 않아 정수 표현을 정하지 않았다. 제안: 100 = 1.0배인 정수 백분율로 저장한다.

### 미디어 profile

- 제안: 구조는 [ADR 0011](decisions/0011-version-media-output-profiles.md)을 따른다. 1080×1920·30fps·H.264 yuv420p와 -16 LUFS를 출발값으로 하며 AAC-LC 48kHz stereo·내부 48kHz float·master -2 dBTP·최종 AAC decode 뒤 -1 dBTP 상한을 검토한다. 현재 12절의 AAC 44.1kHz는 변경하지 않는다.
- 제안: 플랫폼 bitrate를 profile로 나누고 색 변환·encoder·음향 설정을 `core/config/media.yaml`에 모은다. 수치는 공식 플랫폼 합격선이 아니다. -14 LUFS를 공통 공식 규격으로 단정하지 않는다. 실제 픽셀 변환·압축 뒤 음량·peak·A/V sync와 청취·실제 업로드가 필요하다. profile은 관련 cache key에 반영한다.
- 근거: [YouTube encoding](https://support.google.com/youtube/answer/1722171?hl=en), [Instagram media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media), [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html).

### Prompt 파일과 문체

- 제안: [ADR 0018](decisions/0018-store-prompts-as-files.md)의 `core/prompts/` 배치, 변수·schema·예시, loader를 검토한다. 변경 전후 같은 fixture로 품질·계약을 비교하고 prompt digest를 기록·cache에 연결한다. 파일 형식과 loader는 공식 가이드 검토 뒤 정한다.

- 모든 resolved route의 prompt 파일 앞부분에 짧은 `style notes`를 둔다. 언어와 register와 어조와 단어 선택의 이유를 적는다.
- 지시는 원하는 동작으로 쓴다. 각 지시에 이유를 짧게 붙인다. 강조용 all-caps 대신 보통 문장을 쓴다. 기술 식별자는 보존한다.
- 한국어 대본의 지시와 예시는 한국어로 쓴다. 앱에서 선택한 register와 어조를 따른다. 출력에 써도 되는 어휘를 고른다. 목표 말투의 짧은 예시를 1~2개 둔다.
- route마다 검토용 합성 입력을 2~5개 둔다. 입력 파일은 해당 prompt 옆의 `style-fixtures.jsonl`이다. prompt 안 예시와 별개다. §15의 녹화 응답 조회에 사용하지 않는다.
- `scripts/compare_prompt_style.py`는 같은 fixture의 변경 전후 응답 파일을 읽어 HTML 한 페이지의 좌우 칸에 표시한다. renderer는 모델을 호출하지 않는다. fixture ID와 입력과 전후 응답을 함께 보인다. route와 전후 prompt 구분값과 실제 model ID와 effort를 함께 기록한다.
- 비교 응답은 같은 provider와 실제 model ID와 effort와 출력 한도에서 얻는다. 조건이 다르면 페이지에 차이를 표시한다. 최초 작성은 변경 전 응답 없음으로 표시한다. 실패와 누락은 빈 성공값 대신 해당 상태로 표시한다. HTML에 넣는 입력과 응답은 escape한다.
- 검토 페이지는 일반 앱 로그가 아니다. 합성 자료만 쓰고 작업의 로컬 출력 폴더에 둔다. 검토자가 말투와 어휘와 읽기 자연스러움을 확인할 자료다. 절차는 [기여 안내](../CONTRIBUTING.md#prompt-검토)를 따른다. 실제 모델 출력이 없으면 문체 품질 미검증으로 표시한다. 재생 출력은 새 prompt 품질 증거로 쓰지 않는다.
- 제안: 선택 도구 `scripts/lint_prompt_style.py`는 부정 지시만 있는 문장과 강조용 all-caps 후보를 경고한다. 기술 식별자는 예외로 두고 종료 코드는 0이다. 실행 범위와 품질 해석은 [기여 안내](../CONTRIBUTING.md#prompt-검토)를 따른다.
- 신뢰된 지시는 system에 둔다. 사용자 글과 제삼자 자료는 기존 tools-off `text`·`png` 데이터 parts로만 보낸다. 이 방식은 Anthropic의 `tool_result` 권고와 다르다. 이 한계를 문서화하고 tool-result 교환을 도입하지 않는다.

근거: [Anthropic prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)는 원하는 동작과 이유와 출력 문체에 맞춘 prompt와 예시를 권한다. [OpenAI prompting guide](https://developers.openai.com/api/docs/guides/prompt-engineering)는 communication style과 원하는 출력 예시를 명시하도록 권한다. 한국어와 register의 일치와 어휘 선택은 이 앱의 적용 규칙이다. 예시 수와 fixture 수와 비교 도구와 warning-only lint는 이 앱의 작은 검토 설계다. [Anthropic indirect prompt injection 권고](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks)는 제삼자 자료를 `tool_result`로 보내도록 권한다.

### 남은 검증 입력

- 기술 구현 대기: 핵심어 범위 표현, 실행 가능한 schema·OpenAPI, 모듈별 fixture다.
- 기술 검증 대기: 양 OS 설치·sandbox 거부, 선택 TTS 속도·청취, BGM 곡별 권리, 한국어 font, 링크 성공 여부다. Kenney 부위 구조와 컷아웃 호환도 확인한다.
