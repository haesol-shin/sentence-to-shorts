# 관리 안내

이 문서는 병합 담당자의 병합과 cubic 운영 규칙의 원본이다. 기여자는 [CONTRIBUTING](CONTRIBUTING.md)을 따른다.

## 병합

- 필수 CI check가 모두 통과하고 리뷰 지적을 수정하거나 근거 있는 답변으로 해결한 뒤 기본으로 squash 병합한다. 이 조건은 merge 커밋 병합에도 같이 적용한다. 해결하지 않은 지적을 남긴 채 병합하지 않으며 봇의 응답 자체를 지적 해결로 보지 않는다. 자동 병합도 같은 조건을 따른다.
- 병합 담당자는 squash 제목과 본문을 [커밋 형식](CONTRIBUTING.md#커밋-메시지)에 맞춰 새로 쓴다. 브랜치 커밋 메시지 모음은 버리고 변경 전체의 이유를 적는다.
- 따로 나눌 수 없는 큰 변경은 단계 커밋을 남기고 merge 커밋으로 병합한다. 커밋 하나에 담으면 단계별로 읽거나 되돌릴 수 없기 때문이다. merge 커밋 제목은 PR 제목에 `(#번호)`를 붙이고 본문은 비운다.
- cubic을 사용할 수 없으면 같은 diff를 별도 독립 리뷰로 검토하고 판정 증거를 남긴다. 작업 내부의 독립 리뷰는 PR 리뷰로 대체하지 않는다.

## cubic

- trial은 검토한 줄 20,000줄까지이며 전체 재검토는 같은 줄도 다시 센다. 자동 incremental 검토는 끈다. 실행 설정의 원본은 [cubic.yaml](cubic.yaml)이다.
- draft PR, `no-cubic` label이 있는 PR, `agent/`로 시작하는 브랜치의 PR은 자동 검토하지 않는다. 에이전트 작업 브랜치는 병합 전 독립 리뷰를 이미 거쳤고 label을 붙이지 않기 때문이다. 필요할 때 `@cubic-dev-ai review`로 요청한다. 증분 검토는 `@cubic-dev-ai incremental review`로 요청한다.
- 사용량과 지원 설정의 근거: [AI review usage](https://docs.cubic.dev/account/ai-review-usage.md), [cubic.yaml](https://docs.cubic.dev/configure/cubic-yaml.md). timeout과 추가 custom rule은 정하지 않았다.
