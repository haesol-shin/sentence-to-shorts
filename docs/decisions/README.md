# 결정 기록

[MADR 공식 안내](https://adr.github.io/madr/)를 따른다. 확인한 최신 정식 release는 [4.0.0](https://github.com/adr/madr/releases/tag/4.0.0)이다. [minimal template](https://github.com/adr/madr/blob/4.0.0/template/adr-template-minimal.md)에 Status, Date, Basis를 추가했다. 원본의 Context and Problem Statement는 Context로 적는다. Decision Outcome은 Decision으로 적는다. Considered Options와 Consequences도 유지한다. 제목과 본문은 한국어로 쓴다. 파일명은 연속 번호와 영어 kebab-case로 쓴다.

Date는 ADR 작성일이다. 개인 대화의 날짜가 아니다. Basis에는 Team decision 또는 공식 문서 링크를 쓴다. 이유만으로 근거를 대신하지 않는다. 개인 발언과 내부 경로는 공개하지 않는다. Accepted는 확인된 제품·팀 결정이다. Proposed는 아직 확정되지 않은 설계안이다. 채택 상태는 구현이나 검증 완료를 뜻하지 않는다.

결정을 바꾸는 PR은 새 ADR을 추가한다. 새 ADR에는 이전 ADR 링크를 넣는다. 대체된 ADR에는 후속 ADR 링크를 넣는다. index의 상태도 함께 갱신한다. 기존 승인 범위를 넘는 제안은 확정 결정으로 쓰지 않는다. 공개 운영 규칙은 개발 도구와 무관하게 모든 기여자에게 적용한다.

| ADR | 결정 | Status |
|---|---|---|
| [0001](0001-record-decisions-with-adr.md) | ADR과 근거 기록 | Accepted |
| [0002](0002-render-media-with-code.md) | 코드 렌더링과 장면 재생성 | Accepted |
| [0003](0003-separate-llm-providers-and-routing.md) | LLM provider와 실행 profile | Accepted |
| [0004](0004-use-fixture-and-configured-routes.md) | fixture와 세부 라우팅 | Proposed |
| [0005](0005-run-generated-code-in-pyodide-deno.md) | Pyodide on Deno sandbox | Accepted |
| [0006](0006-use-five-steps-and-one-panel.md) | 다섯 단계와 한 패널 UI | Accepted |
| [0007](0007-persist-storage-and-job-state.md) | 저장과 job 모델 | Proposed |
| [0008](0008-select-tts-by-listening.md) | 청취로 TTS 선택 | Accepted |
| [0009](0009-support-uploaded-and-code-bgm.md) | 업로드와 코드 BGM | Accepted |
| [0010](0010-source-bgm-with-redistribution-rights.md) | BGM 출처와 재배포 권리 | Proposed |
| [0011](0011-version-media-output-profiles.md) | 미디어 출력 profile | Proposed |
| [0012](0012-package-for-windows-and-linux.md) | Windows와 Linux 배포 | Accepted |
| [0013](0013-use-public-mainline-repository.md) | 공개 main 중심 저장소 | Accepted |
| [0014](0014-gate-ci-on-brand-leaks-and-sandbox.md) | CI brand·leak·sandbox gate | Proposed |
| [0015](0015-require-pr-merge-conditions.md) | PR 병합 조건 | Accepted |
| [0016](0016-use-selected-design-tokens.md) | 선택한 디자인 token | Accepted |
| [0017](0017-build-react-components-with-gallery.md) | React 컴포넌트와 갤러리 | Accepted |
| [0018](0018-store-prompts-as-files.md) | prompt 파일 배치와 검증 | Proposed |
| [0019](0019-review-every-pr-with-cubic.md) | cubic PR 리뷰 | Accepted |
| [0020](0020-defer-release-api-key-registration.md) | 배포판 API key 등록 보류 | Accepted |
| [0021](0021-defer-brand-name-to-team.md) | 작업 이름 선택과 brand 단일 원본 | Accepted |
| [0022](0022-review-prompt-style-with-small-fixtures.md) | 작은 fixture 묶음으로 prompt 문체 검토 | Proposed |
