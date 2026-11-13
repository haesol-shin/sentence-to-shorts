# 0014 CI의 brand와 leak과 sandbox 검사를 제안한다

## Status

Proposed

## Date

2026-11-14

## Context

이름은 나중에 바뀔 수 있다. 공개 문서와 생성 코드에는 각각 다른 검사가 필요하다.

## Decision

필수 status check를 core, frontend, drift, sandbox, brand로 구성하도록 제안한다. brand 검사는 `core/config/brand.yaml` 밖의 이름 하드코딩을 거절하도록 제안한다. 허용 목록은 `LICENSE`, `.git/`, [이름 결정 기록](0021-defer-brand-name-to-team.md)으로 제한하도록 제안한다. 공개 문서는 내부 경로와 개인 인용을 검사하도록 제안한다. 모든 변경의 diff에는 secret과 leak 검사를 적용하도록 제안한다. sandbox check는 시험 수가 0이면 실패하도록 제안한다. 초기 runtime 존재 시험과 실제 거부 시험의 범위는 구분하도록 제안한다. 실제 거부 시험을 추가하기 전에는 격리 검증 완료로 보고하지 않도록 제안한다. workflow는 최소 권한과 SHA 고정을 사용하도록 제안한다.

## Basis

- Team decision: CI를 사용한다. 구체적인 gate 구성의 승인은 뜻하지 않는다.
- Team decision: 이름은 쉽게 바꿀 수 있어야 한다.
- [GitHub 보안 강화 안내](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions)는 workflow 권한과 action 고정의 근거다.
- [GitHub 필수 status check](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)는 병합 gate 구현의 근거다.

## Considered options

- brand·leak·sandbox 별도 검증: 서로 다른 실패 원인을 드러내므로 제안한다.
- 일반 unit test만 사용: 이름 분산과 정보 노출과 권한 경계를 확인하지 못해 선택하지 않는다.
- 시험이 없는 sandbox job 허용: 거짓 성공을 만들 수 있어 선택하지 않는다.

## Consequences

- 검사 자체가 고의 위반에서 실패하는지 시험해야 한다.
- fixture CI와 실제 생성 검증을 구분해야 한다.
- 공개 ADR의 Date는 기록 작성일이다.
- Date를 개인 대화 날짜로 해석하거나 제거하면 안 된다.
