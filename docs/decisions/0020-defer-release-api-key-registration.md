# 0020 배포판 API key 등록과 실호출을 보류한다

## Status

Accepted

## Date

2026-11-14

## Context

배포 adapter 구현과 유료 API 실호출은 별도 검증이다. 현재 릴리스 빌드에 API key를 등록하지 않기로 했다.

## Decision

현재 release 빌드에는 API key를 등록하지 않는다. `anthropic_api` adapter 구현은 계속한다. adapter는 fake 응답으로 시험한다. release profile의 실제 API 호출 단계는 미실행으로 기록한다. 선택 TTS와 렌더링과 설치 시험은 가능한 범위에서 계속한다. fake 또는 fixture 결과를 실제 API 호출 성공으로 보고하지 않는다.

## Basis

- Team decision: 현재 API key 등록은 하지 않는다.
- Team decision: release 실호출은 미실행으로 기록한다.
- Team decision: `anthropic_api`는 구현하고 fake로 시험한다.

## Considered options

- adapter 구현과 실호출 분리: 자격 증명 없이 구현을 검증할 수 있어 선택한다.
- 빌드용 key 등록: 현재 결정으로 보류한다.
- adapter 구현까지 보류: 제품의 API 연결 구조가 필요해 선택하지 않는다.

## Consequences

- 배포판의 실제 API 연결은 미검증으로 남는다.
- 릴리스 증거는 미실행 항목을 명시해야 한다.
- 향후 실제 호출에는 별도 자격 증명과 검증 실행이 필요하다.
