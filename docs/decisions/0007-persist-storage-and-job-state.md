# 0007 저장과 job 모델을 제안한다

이 문서는 저장과 job 구조 제안의 결정 기록이다.

Status: Proposed | Date: 2026-11-14

## Context

중단·undo·부분 수정 뒤에도 이전 성공 결과를 재사용해야 한다.

## Decision

SQLite index, 불변 revision JSON, 파일 artifact와 영속 job 모델을 제안한다. 상태·queue·복구·경로 세부는 [CONTRACTS 열린 질문](../CONTRACTS.md#저장과-job-구현)의 비구속적 제안이다.

## Consequences

승인 전 구현 세부를 확정 규칙으로 보지 않는다. DB·파일 간 실패 복구와 늦은 응답 거부, 참조 artifact 보호를 검증해야 한다.
