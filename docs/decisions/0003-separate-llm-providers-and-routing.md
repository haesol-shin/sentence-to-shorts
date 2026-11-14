# 0003 LLM provider와 실행 profile을 분리한다

이 문서는 LLM provider와 실행 profile 분리의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

개발 연결과 배포 인증을 같은 제품 코드에서 교체해야 한다.

## Decision

profile과 provider adapter를 분리하고 모델 routing을 지원한다. 배포 기본은 anthropic_api, 개발 기본은 openai_compat이며 공식 claude_cli는 개발 선택지다. 인증·호출 계약은 [CONTRACTS 10](../CONTRACTS.md#10-llm-adapter)을 따른다.

## Consequences

실제 provider·model을 기록한다. 현재 실호출 검증 범위는 [CONTRACTS](../CONTRACTS.md#현재-검증-범위)를 따른다.
