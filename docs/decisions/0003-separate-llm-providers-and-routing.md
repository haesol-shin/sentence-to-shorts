# 0003 LLM provider와 실행 profile을 분리한다

## Status

Accepted

## Date

2026-11-14

## Context

개발 환경의 연결과 배포판의 인증은 다르다. 대본의 품질 요구도 작업마다 다르다.

## Decision

배포판은 `anthropic_api`를 기본으로 쓴다. 사용자는 자기 API key로 인증한다. 현재 빌드의 key 등록과 실호출은 [보류 결정](0020-defer-release-api-key-registration.md)을 따른다. 개발판은 표준 Chat Completions를 호출하는 `openai_compat`를 기본으로 쓴다. endpoint의 `base_url`과 model 이름을 설정한다. 인증이 필요하면 keyring 또는 환경변수에서 key를 읽는다. 각 사용자는 자기 endpoint와 인증을 쓴다. `claude_cli`는 수정하지 않은 공식 CLI를 호출하는 개발용 선택 adapter다. 모델 라우팅을 지원한다. 스토리텔링이 중요한 대본의 상위 모델은 Sonnet 5.5다. 세부 배정은 [별도 제안](0004-use-fixture-and-configured-routes.md)으로 관리한다.

## Basis

- Team decision: 배포판 API key 인증과 개발용 CLI를 구분한다.
- Team decision: 개발판의 기본 연결을 `openai_compat`로 둔다.
- Team decision: 스토리텔링 작업에 상위 모델을 배정한다.
- Team decision: 상위 대본 모델은 Sonnet 5.5로 둔다.
- [Claude Code 법적 준수 안내](https://code.claude.com/docs/en/legal-and-compliance)는 제품 인증의 조건을 설명한다.

## Considered options

- profile과 adapter 분리: 같은 제품 코드로 연결을 교체할 수 있어 선택한다.
- 개발·배포 장기 브랜치 분리: 두 코드가 달라질 위험이 있어 선택하지 않는다.
- 구독 CLI를 배포 기본으로 사용: API key 기본 결정과 맞지 않아 선택하지 않는다.

## Consequences

- 실제 호출한 provider와 model을 실행 증거에 기록해야 한다.
- 모델 ID와 지원 기능은 구현 때 공식 문서로 확인해야 한다.
- CLI 연결의 보안 제한은 별도로 검증해야 한다.
