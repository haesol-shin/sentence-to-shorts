# 기여 안내

이 문서가 기여 규칙의 원본이다. 어떤 개발 도구를 쓰든 같은 규칙을 따른다. 결정의 근거는 [결정 기록](docs/decisions/README.md)에 있다.

## 작업 흐름

- 장기 브랜치는 `main` 하나다. 변경은 `main`에서 만든 짧은 브랜치에서 하고 PR로 제출한다.
- 필수 CI check가 모두 통과해야 한다.
- 리뷰 bot(cubic)의 지적은 수정하거나 근거를 들어 답변한다. 해결하지 않은 지적을 남긴 채 병합하지 않는다. 봇의 응답 자체를 지적 해결로 보지 않는다.
- 병합 방식은 squash다. 자동 병합도 같은 조건을 따른다.
- 결정이 바뀌는 변경은 새 ADR을 추가하고 [결정 기록](docs/decisions/README.md)의 index를 함께 갱신한다. 새 ADR은 대체하는 ADR에 링크한다.

## 커밋 메시지

- 제목은 영어 `type(scope): summary`다. [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)를 따른다.
- 본문에는 변경 이유를 반드시 쓴다. 버린 대안이 있으면 그 이유를 쓴다. 제목과 diff만으로 드러나지 않는 동작 변화만 추가한다.
- 본문 bullet의 개수는 정하지 않는다.
- `git add <path>`로 정확한 경로만 stage한다. 커밋 뒤 `git log -1 --format=%B`로 형식을 확인한다.
- squash 병합 때 커밋 제목과 본문도 이 규칙에 맞춘다.

## Pull request

- PR 제목은 영어로 쓴다. squash 커밋의 제목이 되므로 커밋 제목과 같은 `type(scope): summary` 형식을 쓴다. 본문은 한국어만 쓴다.
- 본문 절은 [PR 템플릿](.github/pull_request_template.md)의 순서를 따른다: 무엇을 왜, 먼저 볼 곳, 확인한 방법, 한계와 남은 일.
- 완료 기준이 필요하면 첫 절에서 설명한다. 별도 절을 만들지 않는다.
- 확인한 방법에는 실제로 실행한 명령과 결과를 쓴다. 실행하지 않은 것은 마지막 절에 미검증으로 적는다.
- 계약 변경이 필요하면 마지막 절에 변경 요청으로 적고 현재 계약으로 끝낸다.
- 결정이 바뀔 때만 새 ADR 링크 한 줄을 본문에 덧붙인다.
- 화면 변경에는 390px과 1440px 스크린샷을 붙인다.
- 공개 문구(PR, 커밋, 코드 주석, 문서)에는 로컬 경로, 개인 이름, 실제 사용자 자료를 넣지 않는다. 증거는 합성 자료만 쓴다. `scripts/check_public_docs.py`가 내부 경로와 개인 인용과 개인 도구 표기를 찾아 실패시킨다.

## Markdown

- 문단과 목록 항목은 한 줄로 쓰고 줄바꿈은 에디터에 맡긴다.
- em-dash를 쓰지 않는다.
- CI가 `scripts/check_public_docs.py`로 검사한다. 코드 블록, 표, HTML 블록, front matter, 줄 끝 두 칸이나 역슬래시로 쓴 의도적 줄바꿈은 검사하지 않는다.

## 이름

서비스와 저장소 이름은 `core/config/brand.yaml`에만 쓴다. 다른 파일은 그 값을 읽는다. `scripts/check_brand.py`가 CI에서 확인한다.

## 명령

저장소 root에서 실행한다. `uv`가 필요하다. 검사 스크립트의 의존성은 실행할 때마다 격리 환경에 설치되므로 `pyproject.toml`이 필요 없다.

```sh
python scripts/check_brand.py
uv run --with markdown-it-py==3.0.0 python scripts/check_public_docs.py
uv run --with markdown-it-py==3.0.0 python -m unittest discover -s scripts/tests
```

`core/`의 Python 프로젝트가 저장소에 들어온 뒤에는 아래 명령도 쓴다.

```sh
cd core && poetry install && poetry run ruff check . && poetry run lint-imports && poetry run pytest tests/contracts tests/architecture -q
```

변경과 관련된 시험을 먼저 실행한다. 전체 시험은 CI가 한 번 실행한다. 시험 함수 이름은 `test_<criterion>_<behavior>`다.

## AI 사용

도구 사용은 환영한다. 작성자가 변경을 이해하고 검증할 책임을 진다.
