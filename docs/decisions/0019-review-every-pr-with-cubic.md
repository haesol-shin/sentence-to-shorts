# 0019 모든 PR에 cubic 리뷰를 적용한다

## Status

Accepted

## Date

2026-11-14

## Context

작업 내부 리뷰와 공개 PR 리뷰는 확인하는 시점이 다르다. 리뷰 봇은 독립 구현 검증을 대체하지 않는다.

## Decision

cubic을 모든 PR의 리뷰 봇으로 사용한다. 작업 내부의 독립 리뷰도 유지한다. cubic을 사용할 수 없으면 같은 diff를 별도 독립 리뷰로 검토한다. 필수 CI 통과와 cubic 지적의 해결 또는 답변을 확인한 뒤 승인 범위에서 병합한다. 세부 timeout과 추가 custom rule은 이 ADR에서 확정하지 않는다.

## Basis

- Team decision: 모든 PR은 cubic으로 리뷰한다.
- Team decision: cubic이 제한되면 별도 독립 리뷰로 전환한다.

## Considered options

- cubic과 독립 작업 리뷰: 작업 검증과 PR 지적 확인을 나눌 수 있어 선택한다.
- cubic만 사용: 별도 구현·리뷰 세션 결정과 맞지 않아 선택하지 않는다.
- 모든 PR의 사람 사전 리뷰: 승인된 자동 병합 범위에는 필수로 두지 않는다.

## Consequences

- 봇 설치와 접근 권한은 별도로 확인해야 한다.
- 무료 제공 조건과 한도는 실제 사용 때 확인해야 한다.
- 대체 리뷰가 실행되면 같은 diff의 판정 증거를 남겨야 한다.
