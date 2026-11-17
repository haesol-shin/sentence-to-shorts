# 0024 서버 모드와 개인 모드에서 자료를 소유자별로 나눈다

Status: Accepted | Date: 2026-11-17

## Context

여러 사용자가 한 서버를 쓰는 모드를 먼저 지원하고 개인 설치도 유지한다. [0007](0007-persist-storage-and-job-state.md)의 저장과 job 모델은 한 사용자 기준이었다.

## Decision

0007의 모델을 쓰고 소유 경계를 더한다. 모든 사용자 자료는 `owner_id`로 나누고 artifact 조회는 `(owner_id, cache_key)`로 한다. API key는 소유자와 provider마다 credential 하나로 저장하고 LLM 호출 때 job 소유자로 찾는다. 개인 모드는 SQLite와 pairing, 서버 모드는 OIDC와 PostgreSQL을 쓴다. 외부 신원 `(issuer, subject)`는 내부 계정에 대응한다. 여러 worker는 lease로 job을 점유한다. 세부는 [CONTRACTS](../CONTRACTS.md)를 따른다.

## Consequences

모든 객체 경로에 소유 검사 시험이 필요하다. 서버 모드는 두 DB backend를 함께 시험한다. 공유 CAS, 객체 저장소, 별도 broker, 자동 확장은 이 경계 위에서 나중에 붙인다.
