# 0011 버전이 있는 미디어 profile을 제안한다

이 문서는 미디어 profile 구조 제안의 결정 기록이다.

Status: Proposed | Date: 2026-11-14

## Context

encoder·색·음향 설정 변경은 여러 단계의 cache와 출력 검증에 영향을 준다.

## Decision

버전 profile을 core/config/media.yaml 한 곳에 두는 구조를 제안한다. 수치와 검증안은 [CONTRACTS 열린 질문](../CONTRACTS.md#미디어-profile)에 둔다.

## Consequences

문서 리뷰만으로 승인되지 않는다. profile 변경을 cache key에 반영하고 실제 픽셀 변환과 최종 AAC의 음량·peak·A/V sync를 검증한다. 실제 업로드·청취를 CI로 대체하지 않는다.
