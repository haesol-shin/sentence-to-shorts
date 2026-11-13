# 0002 영상은 코드로 렌더링한다

이 문서는 코드 렌더링 구조의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

부분 수정에서 바뀌지 않은 장면을 보존해야 한다.

## Decision

LLM은 장면 데이터를 만들고 템플릿 코드가 렌더한다. 새 스타일·템플릿 코드는 저장해 재사용한다. 생성 모델 제외 범위는 [INTENT](../INTENT.md#하지-않는-것-non-goals-mvp)를 따른다.

## Consequences

장면별 artifact와 변경 범위를 관리한다. 생성 코드는 [sandbox](0005-run-generated-code-in-pyodide-deno.md)를 따른다.
