# AGENTS

이 문서는 실행 명령과 코드에서 보이지 않는 함정만 둔다. 기여 규칙은 [CONTRIBUTING](CONTRIBUTING.md)이 원본이다.

## 명령

전체 명령은 [CONTRIBUTING의 명령](CONTRIBUTING.md#명령)에 있다. 빠른 확인은 아래와 같다.

```sh
python scripts/check_brand.py
uv run --with markdown-it-py==3.0.0 python scripts/check_public_docs.py
```

## 저장소 규칙

- 작업이 허용한 경로 밖은 고치지 않는다.
- 공통 계약(`schemas/`, `core/app/schemas/`, `core/app/ports.py`, `core/config/`, `fixtures/`)은 [docs/CONTRACTS.md](docs/CONTRACTS.md)가 기준이다. 계약 변경은 계약 변경 PR에서만 한다.
- 디자인 부품(`frontend/src/components/`, `frontend/src/gallery/`, `frontend/tests/gallery/`)은 디자인 작업만 바꾼다.
- 이름 규칙은 [CONTRIBUTING.md의 이름 절](CONTRIBUTING.md#이름)을 따른다.
- 대화 내용과 반복 작업 이력, 작업 ID, 리뷰 기록을 코드 주석과 커밋과 PR 글에 옮기지 않는다.
- Markdown 문장에 em-dash를 넣지 않는다. 생성한 문장을 붙일 때 특히 확인한다.
- 격리 실행의 데이터와 cache는 `.local/` 아래에 둔다. 임시 파일은 끝나기 전에 지운다.
