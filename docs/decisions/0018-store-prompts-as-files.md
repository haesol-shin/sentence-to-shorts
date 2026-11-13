# 0018 prompt를 코드 밖 파일로 분리한다

이 문서는 prompt 파일 분리 구조의 결정 기록이다.

Status: Proposed | Date: 2026-11-14

## Context

prompt 문구는 실행 코드와 별도로 바뀐다.

## Decision

파일 분리 원칙은 확정이다. core/prompts/ 배치·trusted 지시와 데이터 분리·변수·schema·예시·loader·digest 검증은 [CONTRACTS 열린 질문](../CONTRACTS.md#prompt-파일과-문체)의 제안이다.

## Consequences

파일 형식과 loader는 공식 가이드 검토 뒤 정한다. 문체 검토 절차는 [CONTRIBUTING](../../CONTRIBUTING.md#prompt-검토)에 두고 사용자 prompt를 기본 로그에 수집하지 않는다.
