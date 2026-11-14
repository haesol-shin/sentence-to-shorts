# 0005 생성 코드는 Pyodide on Deno에서 실행한다

이 문서는 생성 코드 실행 경계의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

생성 코드는 신뢰할 수 없지만 새 형태와 음악 표현에 필요하다.

## Decision

Pyodide on Deno를 사용하고 bootstrap 뒤 권한을 회수한다. 외부 감독이 시간·출력을 제한한다. host import·exec 우회는 없다. PNG 부품과 WAV만 반환하고 host Pillow가 합성한다.

## Consequences

양 OS 거부 시험과 부모 출력 검증이 필요하다. OS hard cap 미적용은 미확인으로 기록하며 RSS 관찰로 보장하지 않는다. 세부는 [CONTRACTS 9](../CONTRACTS.md#9-sandbox)를 따른다.
