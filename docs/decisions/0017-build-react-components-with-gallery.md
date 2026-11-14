# 0017 실제 React 부품과 개발용 갤러리를 사용한다

이 문서는 React 부품과 갤러리 구조의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

정적 시안과 실제 구현을 따로 유지하면 차이가 생긴다.

## Decision

frontend/src/components/의 실제 React 부품을 앱의 개발 전용 /gallery에서 검토하고 승인된 부품을 재사용한다. 별도 Storybook은 두지 않는다.

## Consequences

390px·1440px에서 default·hover·pressed·disabled·loading·error를 독립 검토하고 사람 확인 뒤 token·부품·기준 화면을 고정한다. 갤러리는 공개하지 않는다. 디자인 확인 대기는 디자인 작업만 멈춘다. 새 부품도 같은 절차를 따른다.
