# 0016 선택한 디자인 token을 공통으로 사용한다

## Status

Accepted

## Date

2026-11-14

## Context

공통 token이 없으면 컴포넌트의 모양과 간격이 달라질 수 있다. 기본 시각 값은 사람의 선택을 따라야 한다.

## Decision

UI 글꼴은 Pretendard다. accent는 `#3182F6`이다. 카드 radius는 36px다. 모양은 세 종류다. 버튼, 칩, 한 줄 입력창, 토글은 capsule(높이의 절반)이다. 보내기 버튼은 원이다. 썸네일, 설정 묶음, 안쪽 패널은 concentric이며 `max(바깥 radius - padding, 16px)`로 계산해 카드 안에서 16px다. 카드, sheet, dialog는 fixed이며 radius 단계는 16, 24, 36, 48px다. 여러 줄 입력창은 radius 24px를 유지한다. 카드 안쪽 요소는 그림자 없이 면 색 `#F2F4F6`으로 구분한다. 카드 그림자는 진한 강도를 쓴다. 선택한 그림자의 시작값은 y 12px와 blur 32px와 불투명도 16%다. 카드 안쪽 padding은 20px다. 요소 간격은 12px다. 이 값은 공통 token에서 사용한다. 정렬, 화면 배치, 나머지 token은 이 결정으로 확정하지 않는다.

## Basis

- Team decision: Pretendard와 `#3182F6`을 사용한다.
- Team decision: 카드 모양은 radius 36과 진한 그림자와 padding 20으로 정한다. 안쪽 요소는 면 색으로 구분한다.
- [Apple WWDC25, Get to know the new design system](https://developer.apple.com/videos/play/wwdc2025/356): fixed, capsule, concentric 세 모양과 concentric radius는 부모 radius에서 padding을 뺀다는 설명.
- [Pretendard 공식 저장소](https://github.com/orioncactus/pretendard)는 글꼴과 OFL 라이선스의 근거다.
- [WCAG 대비 기준](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)은 accent 위 글자 대비 검사의 기준이다.

## Considered options

- 선택한 공통 token: 선택된 시각 방향을 유지하므로 사용한다.
- radius 16px: 후속 radius 24px 선택으로 대체한다.
- radius 24px: 안쪽 radius가 4px로 작아져 바깥과 곡률이 달라 보여 36px로 대체한다.
- 카드 32px와 안쪽 12px: 입력창과 카드 곡률 차이가 더 커 보여 고르지 않았다.
- 안쪽 1px 테두리와 안쪽 그림자: 면 색 구분을 골랐다.
- 컴포넌트별 임의 값: 디자인 일관성을 해쳐 선택하지 않는다.

## Consequences

- 작은 글자는 accent 배경에서 별도 대비 검수가 필요하다.
- token 선택은 모든 컴포넌트 승인과 같지 않다.
- 최종 화면과 상태별 검토를 계속 수행해야 한다.
