# 0007 저장과 job 모델을 쓴다

이 문서는 저장과 job 구조의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

중단·undo·부분 수정 뒤에도 이전 성공 결과를 재사용해야 한다.

## Decision

SQLite index, 불변 revision JSON, 파일 artifact와 영속 job 모델을 쓴다. 상태·queue·복구·경로 세부는 [CONTRACTS 열린 질문](../CONTRACTS.md#저장과-job-구현)에 있으며 계약 본문으로 옮길 때 확정한다.

## Consequences

열린 질문에 남은 job 세부는 계약 본문으로 옮기기 전까지 확정 규칙으로 보지 않는다. DB·파일 간 실패 복구와 늦은 응답 거부, 참조 artifact 보호를 검증해야 한다. 소유 경계, 서버 모드 DB, lease 점유는 [0024](0024-scope-data-by-owner-in-server-and-personal-modes.md)가 더한다.
