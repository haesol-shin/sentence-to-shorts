# 0016 공통 디자인 token을 사용한다

이 문서는 공통 디자인 token 체계의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

컴포넌트마다 모양과 간격이 달라지지 않아야 한다.

## Decision

공통 token: Pretendard, accent #3182F6, 카드 radius 36px·padding 20px·gap 12px. capsule은 버튼·칩·한 줄 입력·토글의 높이/2, 보내기는 원이다. concentric은 썸네일·설정 묶음·안쪽 패널에 max(부모 radius-padding,16px), 카드 안은 16px다. fixed는 카드·sheet·dialog에 16/24/36/48px다. 여러 줄 입력은 24px다. 안쪽은 그림자 없이 #F2F4F6, 카드 그림자는 y12·blur32·opacity16%다.

## Consequences

나머지 token은 미확정이다. 화면 배치는 [SPEC 10a](../SPEC.md#10a-화면-상태-ux-states)를 따른다. accent 위 작은 글자 대비와 상태별 화면을 검수한다. token 채택은 컴포넌트 승인이 아니다.
