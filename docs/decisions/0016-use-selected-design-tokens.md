# 0016 공통 디자인 token을 사용한다

이 문서는 공통 디자인 token 체계의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

컴포넌트마다 모양과 간격이 달라지지 않아야 한다.

## Decision

공통 token: Pretendard, 대표색 `primary` #22262B, 카드 radius 24px·padding 20px·gap 12px. radius 단계는 36, 24, 18, 16, 12, 8과 알약이다. 대화 칸과 작업 칸 같은 패널은 36, 창과 메뉴 판과 카드는 24, 메뉴 줄은 18, 알림은 22, 안내 문장과 파일 칩과 대사 줄과 판 안의 그림 카드는 16, 미리보기와 장면 썸네일은 12, 칩 속 그림은 8이고, 입력창은 첫 화면 24, 대화 칸 28이다. capsule은 버튼·칩·한 줄 입력·토글의 높이/2, 보내기는 원이다. concentric은 썸네일·설정 묶음·안쪽 패널에 max(부모 radius-padding,16px), 카드 안은 16px다. 안쪽은 그림자 없이 #F2F4F6, 카드 그림자는 y12·blur32·opacity16%다.

## Consequences

대표색 token 이름은 [ADR 0023](0023-build-components-on-shadcn-base-ui.md)에서 `primary`로 바뀌었다. 나머지 token은 미확정이다. 화면 배치는 [SPEC 10a](../SPEC.md#10a-화면-상태-ux-states)를 따른다. 강조색 위 작은 글자 대비와 상태별 화면을 검수한다. token 채택은 컴포넌트 승인이 아니다.
