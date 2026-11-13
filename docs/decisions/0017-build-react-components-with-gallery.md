# 0017 실제 React 컴포넌트로 갤러리를 만든다

## Status

Accepted

## Date

2026-11-14

## Context

정적 시안을 별도로 만들면 실제 구현으로 옮길 때 차이가 생길 수 있다. 공통 컴포넌트의 상태를 같은 자리에서 검토해야 한다.

## Decision

공통 부품은 `frontend/src/components/`의 실제 React 컴포넌트로 만든다. 앱 안의 개발용 `/gallery` route에서 상태별로 보여 준다. 별도 Storybook 의존성을 추가하지 않는다. 갤러리는 개발 profile에서만 제공한다. 공개로 노출하지 않는다. 390px와 1440px 화면을 캡처한다. 구현과 분리한 평가 세션이 기준별로 검토한다. 사람의 확인 뒤 token과 컴포넌트와 기준 스크린샷을 고정한다. 승인된 부품을 제품 화면에 재사용한다. 디자인 확인 대기는 디자인 작업만 멈춘다.

## Basis

- Team decision: 공통 컴포넌트를 먼저 정하고 재사용한다.
- Team decision: 정적 HTML 대신 실제 React 컴포넌트와 개발용 갤러리를 사용한다.
- Team decision: 독립 평가와 사람의 디자인 확인을 거친다.
- [React 컴포넌트 문서](https://react.dev/learn/your-first-component)는 재사용 부품 구현의 기준이다.
- [Playwright 시각 비교](https://playwright.dev/docs/test-snapshots)는 기준 스크린샷 검사의 근거다.

## Considered options

- 실제 React와 앱 안 갤러리: 승인된 시안과 구현이 같은 코드라 선택한다.
- 정적 HTML 뒤 React 재구현: 두 코드의 차이가 생겨 선택하지 않는다.
- 별도 Storybook: 현재 요구에는 추가 의존성을 두지 않는다.

## Consequences

- default와 hover와 pressed와 disabled와 loading과 error 상태를 검토해야 한다.
- 스크린샷 검사는 사람의 디자인 판단을 대체하지 않는다.
- 새 공통 부품도 같은 검토 절차를 따라야 한다.
