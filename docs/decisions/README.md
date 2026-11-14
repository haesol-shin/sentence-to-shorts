# 결정 기록

이 문서는 되돌릴 때 코드나 데이터 전반의 재작업이 필요한 구조 결정만 ADR로 관리한다.

[MADR minimal template](https://github.com/adr/madr/blob/4.0.0/template/adr-template-minimal.md)의 Context·Decision·Consequences를 짧게 쓰고 대안은 필요할 때 한 줄로 덧붙인다. Status는 Accepted 또는 Proposed이며 Date는 기록 작성일이다. Proposed는 문서 검토만으로 승인되지 않고 Accepted도 구현·검증 완료를 뜻하지 않는다. 공개 근거는 공식 문서로 연결하고 개인 발언과 내부 경로는 넣지 않는다.

파일명은 `NNNN-kebab-title.md`이며 기존 번호는 유지한다. 구조 변경은 새 ADR에서 이전 ADR을 링크하고 대체된 ADR과 index도 후속 ADR을 링크한다. 제품·UX·기여·관리 절차는 [문서 역할](../../CONTRIBUTING.md#문서-역할)의 원본 문서에 두고 이곳에 복제하지 않는다.

| ADR | 구조 결정 | Status |
|---|---|---|
| [0002](0002-render-media-with-code.md) | 영상은 코드로 렌더링한다 | Accepted |
| [0003](0003-separate-llm-providers-and-routing.md) | LLM provider와 실행 profile을 분리한다 | Accepted |
| [0005](0005-run-generated-code-in-pyodide-deno.md) | 생성 코드는 Pyodide on Deno에서 실행한다 | Accepted |
| [0007](0007-persist-storage-and-job-state.md) | 저장과 job 모델을 제안한다 | Proposed |
| [0011](0011-version-media-output-profiles.md) | 버전이 있는 미디어 profile을 제안한다 | Proposed |
| [0012](0012-package-for-windows-and-linux.md) | Windows와 Linux 설치물을 제공한다 | Accepted |
| [0013](0013-use-public-mainline-repository.md) | 공개 단일 main 저장소를 사용한다 | Accepted |
| [0016](0016-use-selected-design-tokens.md) | 공통 디자인 token을 사용한다(대표색 이름은 [0023](0023-build-components-on-shadcn-base-ui.md)) | Accepted |
| [0017](0017-build-react-components-with-gallery.md) | 실제 React 부품과 개발용 갤러리를 사용한다 | Accepted |
| [0018](0018-store-prompts-as-files.md) | prompt를 코드 밖 파일로 분리한다 | Proposed |
| [0023](0023-build-components-on-shadcn-base-ui.md) | shadcn/ui on Base UI로 화면 부품을 만든다 | Accepted |
