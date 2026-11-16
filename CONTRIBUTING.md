# 기여 안내

이 문서는 기여 절차와 커밋·PR 규칙의 원본입니다. 어떤 개발 도구를 쓰든 같은 규칙을 따릅니다. 병합 담당자는 [관리 안내](MAINTAINING.md)를 따릅니다.

## 작업 흐름

- 저장소 모델은 [ADR 0013](docs/decisions/0013-use-public-mainline-repository.md)을 따릅니다. 변경은 `main`에서 만든 짧은 브랜치에서 PR로 제출해 주세요. 미완성 기능은 PR 브랜치 빌드로 시험합니다.
- 필수 CI check는 workflow마다 집계 job 하나입니다. 필수 check는 `gate | ci`와 `gate | pr title`입니다. 집계 job 이름을 바꾸면 저장소 설정의 필수 check도 같은 날 바꿉니다.
- PR CI는 변경이 덮는 시험만 돌리고, `main` push는 전체 시험을 돌립니다. 어느 시험을 돌릴지는 [시험 선택](scripts/select_tests.py)과 [map](scripts/test_selection.json)이 정합니다.
- 구조 결정을 바꾸는 변경만 새 ADR과 [index](docs/decisions/README.md)를 갱신합니다. 새 ADR은 대체하는 ADR에 링크합니다. 제품·UX·기여 절차 변경은 해당 원본 문서만 고칩니다.

## 리뷰 bot

- cubic은 draft가 아닌 PR을 자동으로 검토합니다. 지적은 P0부터 P3까지 우선순위가 붙습니다.
- P0와 P1은 병합 전에 고칩니다. 오탐이라고 판단하면 근거를 답글로 남깁니다. 해결 처리는 병합 담당자가 합니다.
- P2와 P3은 고치거나, 이유를 답글로 남기거나, `review-followup` 라벨 이슈로 남기고 답글에 링크합니다. 셋 중 하나 없이 병합하지 않습니다.
- 푸시한 뒤 cubic이 고쳐졌다고 판단한 스레드는 자동으로 해결 처리됩니다. 봇이 답했다는 사실만으로 해결된 것으로 보지 않습니다.
- cubic 사용량이 차서 검토가 멈추면 병합 담당자가 같은 diff를 독립 리뷰로 대신합니다. 그 리뷰의 지적은 수정하거나 근거를 들어 답변합니다.
- `agent/*`와 `dependabot/*` 브랜치는 자동 검토하지 않습니다. 실행 설정의 원본은 [cubic.yaml](cubic.yaml)입니다.

## Pull request

- PR 제목은 영어 `type(scope): summary` 형식입니다. 본문 절 제목은 템플릿의 영어 제목을 쓰고, 내용은 한국어로 씁니다.
- 본문 절은 [PR 템플릿](.github/pull_request_template.md)의 순서를 따릅니다: What and Why, Testing, Limitations.
- What and Why는 첫 문단에 푸는 문제와 이 방법을 고른 이유를 쓰고, 이어서 바뀐 동작을 bullet 5개 이하로 씁니다. 버린 대안이 있으면 이유와 함께 씁니다. 파일별 변경 목록은 diff로 대신합니다. 같은 내용을 두 절에 나눠 쓰지 않습니다.
- 완료 기준이 필요하면 첫 절에서 설명합니다. 별도 절은 만들지 않습니다.
- Testing에는 실제로 실행한 명령과 결과를 씁니다. 실행하지 않은 것은 Limitations에 미검증으로 적습니다.
- 현재 작업을 막는 계약 공백은 그 작업에서 고칩니다. PR이 `docs/CONTRACTS.md`와 영향받는 호출자와 fixture를 함께 고치고 What and Why에 그 사실을 씁니다.
- 현재 작업을 막지 않는 계약 변경 요청은 `contract` 라벨을 붙인 이슈로 남깁니다. Limitations에는 `Contract request: #N`과 현재 영향을 쓰고, 요청이 없으면 `Contract request: none`이라고 씁니다. 계약 갱신 PR이 아닌 PR은 계약 이슈에 `Closes #N`을 쓰지 않습니다.
- 구조 결정을 바꿀 때만 새 ADR 링크 한 줄을 본문에 덧붙입니다.
- 화면 변경에는 390px과 1920px 스크린샷을 붙여 주세요.
- 공개 문구(PR, 커밋, 코드 주석, 문서)에는 로컬 경로, 개인 이름, 실제 사용자 자료를 넣지 않습니다. 증거는 합성 자료만 씁니다. `scripts/check_public_docs.py`가 모든 Markdown, `.github/` 아래 workflow YAML, `cubic.yaml`의 내부 경로와 개인 인용과 개인 도구 표기를 검사합니다. PR 본문 자체와 커밋 메시지와 코드 주석은 작성자와 리뷰어가 직접 확인합니다.

### 계약 변경 요청

- 새 요청을 쓰기 전에 열린 이슈와 닫힌 이슈를 `contract` 라벨로 검색합니다. 절 번호(`§14.2`)와 심볼(`VoiceService.timing`)로 찾고 결과를 끝까지 확인합니다.
- 같은 문제가 이미 있으면 새 증거나 다른 대안을 댓글로 더합니다. 다른 문제면 [계약 변경 템플릿](.github/ISSUE_TEMPLATE/contract.md)으로 새 이슈를 만듭니다.
- 이슈 하나는 독립적으로 판단하고 닫을 수 있는 변경 하나입니다. 두 절에 함께 적용해야 하는 변경은 두 절을 밝힌 이슈 하나로 만듭니다.
- 제목은 영어 `contract: <problem> (§N)` 형식입니다. 본문에는 최신 제안을 두고, 제안이 바뀌면 댓글이 아니라 본문을 고칩니다. 이슈를 처리하는 사람은 본문과 모든 댓글을 읽습니다.
- 같은 요청이 이미 있으면 `Duplicate of #N` 댓글을 남기고, 중복 이슈에만 있는 증거를 남길 이슈로 옮긴 뒤 중복 이슈를 닫습니다.

### 계약 갱신 PR

- 계약 이슈는 번호가 가장 낮은 열린 milestone `Contract update N`에 넣습니다. 예를 들어 `Contract update 1`입니다.
- 한 milestone의 요청은 계약 갱신 PR 하나에서 함께 적용합니다. 그 PR이 시작되면 milestone은 새 이슈를 받지 않고, 이후 요청은 `Contract update N+1`로 갑니다. 열린 계약 갱신 PR은 한 번에 하나입니다.
- 계약 갱신 PR은 실제로 적용한 이슈에만 `Closes #N`을 씁니다. 거절한 이슈는 이유를 남기고 미계획으로 닫습니다. 연기한 이슈는 다음 milestone으로 옮깁니다.
- 계약 갱신 PR은 milestone의 `contract` 이슈가 모두 적용·거절·이동 중 하나로 정리되고, PR이 병합되고, 생산자·소비자·fixture·생성 코드를 함께 갱신했을 때 끝납니다.

## 커밋 메시지

- 제목은 영어 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) 형식인 `type(scope): summary`입니다.
- 본문에는 변경 이유를 반드시 씁니다. 버린 대안이 있으면 그 이유도 씁니다. 제목과 diff만으로 드러나지 않는 동작 변화만 추가합니다.
  - 나쁜 예(제목과 diff를 되풀이함): `- Measure forced alignment on Korean and English CPU audio`
  - 좋은 예(diff로 안 보이는 이유): `- Map display phrases to spoken words so captions follow speech`
- 이유가 없는 항목은 빼고, 항목 수를 채우지 않습니다.
- 제목과 본문 사이에는 빈 줄 하나를 둡니다. 본문은 `-` bullet이며 항목마다 한 줄, 최대 72자입니다. 이어 쓰는 줄, 항목 사이 빈 줄, trailer는 넣지 않습니다. 항목은 5개 이하이고 보통 2~4개입니다.
- 따로 나눌 수 없는 큰 변경은 커밋마다 시험이 통과하는 단계로 나눠 주세요. 이런 PR은 단계 커밋을 남겨 병합합니다([관리 안내](MAINTAINING.md#병합)).
- `git add <path>`로 정확한 경로만 stage합니다.

PR 커밋은 `scripts/check_commit_messages.py`가 CI에서 검사합니다.

## 명령

저장소 root에서 실행합니다. `uv`가 필요합니다. 검사 스크립트의 의존성은 실행할 때마다 격리 환경에 설치되므로 `pyproject.toml`이 필요 없습니다.

```sh
python scripts/check_brand.py
uv run --with markdown-it-py==3.0.0 python scripts/check_public_docs.py
uv run --with markdown-it-py==3.0.0 python -m unittest discover -s scripts/tests
python scripts/check_commit_messages.py --range <base>..<head>
```

`core/`의 Python 프로젝트가 저장소에 들어온 뒤에는 아래 명령도 씁니다.

```sh
cd core && poetry install && poetry run ruff check . && poetry run lint-imports && poetry run pytest tests/contracts tests/architecture tests/tools -q
```

변경과 관련된 시험을 먼저 실행합니다. PR CI는 map이 고른 시험을, `main` push는 전체 시험을 돌립니다. 고른 시험을 로컬에서 보려면 `git diff --name-only origin/main...HEAD | python scripts/select_tests.py`를 실행합니다. 시험 함수 이름은 `test_<criterion>_<behavior>`입니다.

## Markdown

- 문단과 목록 항목은 한 줄로 쓰고 줄바꿈은 에디터에 맡깁니다.
- CI가 `scripts/check_public_docs.py`로 검사합니다. 코드 블록, 표, HTML 블록, front matter, 줄 끝 두 칸이나 역슬래시로 쓴 의도적 줄바꿈은 검사하지 않습니다.

## 이름

이름 설정과 실행 값의 원본은 [CONTRACTS 6.1](docs/CONTRACTS.md#61-root)입니다. 이름을 바꾸면 하드코딩 예외인 두 README도 함께 갱신해 주세요.

## AI 사용

도구 사용은 환영합니다. 작성자가 변경을 이해하고 검증할 책임을 집니다.

## Prompt 검토

문체 lint는 작성자가 로컬에서 직접 실행하고 비교 페이지도 로컬에서만 만듭니다. 문체 검사는 CI에서 경고로도 실행하지 않으며 필수 check와 병합 gate로 삼지 않습니다. 경고는 의미 품질 판정이 아닙니다. 구현안은 [CONTRACTS 열린 질문](docs/CONTRACTS.md#prompt-파일과-문체)을 따릅니다.

## 문서 역할

| 문서 | 역할 |
|---|---|
| README | 제품 소개와 실행 안내 |
| [INTENT](docs/INTENT.md) | 목적, 사용자, 제약, 범위 밖 |
| [SPEC](docs/SPEC.md) | 확정된 사용자 동작과 완료 기준 |
| [CONTRACTS](docs/CONTRACTS.md) | 모듈 간 데이터·API·job·저장 계약 |
| DESIGN.md | 시각 규칙과 token (디자인 작업에서 추가) |
| [decisions](docs/decisions/README.md) | 되돌리기 어려운 구조 결정 |
| [GLOSSARY](docs/GLOSSARY.md) | 용어 |
| CONTRIBUTING.md | 기여 절차와 커밋·PR 규칙 |
| [MAINTAINING](MAINTAINING.md) | 병합 담당자와 cubic 운영 규칙 |
| [AGENTS](AGENTS.md) | 실행 명령과 코드에서 보이지 않는 함정 |

한 내용은 한 문서에만 두고 나머지는 링크합니다. 미확정 제안도 주제의 원본 문서 마지막 「열린 질문」에 두고, 확정되면 본문으로 옮깁니다.

## 열린 질문

- workflow는 최소 권한을 유지합니다. action은 full SHA로 고정합니다. 검사 자체도 고의 위반에서 실패하는지 시험합니다. diff의 secret·leak 검사도 적용합니다. sandbox 시험 수가 0이면 실패시킵니다. runtime 존재 시험을 실제 거부 시험의 증거로 쓰지 않습니다.
