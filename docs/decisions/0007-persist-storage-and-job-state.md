# 0007 SQLite와 불변 revision 기반 작업 모델을 제안한다

## Status

Proposed

## Date

2026-11-14

## Context

중단된 생성 작업을 재개해야 한다. 부분 수정과 undo가 이전 성공 결과를 잃게 해서는 안 된다.

## Decision

SQLite `state.db`에 프로젝트 index와 job과 artifact index를 저장하도록 제안한다. 영상 설정은 불변 revision JSON으로 저장하도록 제안한다. 큰 artifact는 파일로 보관하도록 제안한다. job 상태는 queued, running, succeeded, failed, cancelling, cancelled로 나누도록 제안한다. 상태 점유는 원자적으로 전환하도록 제안한다. 취소 뒤 도착한 결과는 버리도록 제안한다. 검증된 artifact만 checkpoint로 기록하도록 제안한다. 재시작 때 존재와 digest를 재검사하도록 제안한다. light queue와 heavy queue는 각각 한 작업만 실행하도록 제안한다. 데이터와 cache는 저장소 밖의 OS별 사용자 디렉터리에 두도록 제안한다.

승인 전에는 이 ADR과 CONTRACTS에 적힌 SQLite index, 불변 revision JSON, artifact 파일 배치, job 상태·queue·복구 세부를 기술 제안으로 읽는다. 재시작 뒤 성공 결과와 마지막 저장 상태를 재사용한다는 결정과 구현 세부의 승인은 구분한다.

## Basis

- Team decision: 성공 결과와 마지막 저장 상태를 재시작 뒤 재사용한다. 저장 구현의 세부 승인은 뜻하지 않는다.
- [SQLite transaction 문서](https://sqlite.org/lang_transaction.html)는 원자적 상태 변경의 기반이다.
- [XDG Base Directory 명세](https://specifications.freedesktop.org/basedir-spec/latest/)는 Linux 사용자 데이터와 cache 위치를 구분한다.

## Considered options

- SQLite index와 파일 artifact: 추가 서버 없이 영속 작업을 관리하는 안으로 제안한다.
- 메모리 큐만 사용: 강제 종료 뒤 상태가 사라져 선택하지 않는다.
- Redis와 Celery: 로컬 MVP에 별도 서비스를 추가해 선택하지 않는다.

## Consequences

- DB와 artifact 파일 사이의 실패 복구를 시험해야 한다.
- revision과 undo가 참조하는 artifact는 cache 청소에서 보호해야 한다.
- 과거 작업의 늦은 응답을 거절하는 시험이 필요하다.
