# 0013 공개 단일 main 저장소를 사용한다

이 문서는 공개 단일 main 저장소 모델의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

개발·배포 장기 브랜치를 나누면 제품 코드가 갈라진다.

## Decision

개인 GitHub의 공개 저장소로 처음부터 운영하고 장기 브랜치는 main 하나만 둔다. 코드 라이선스는 Apache-2.0이다.

## Consequences

모델·음원·글꼴 권리는 코드 라이선스로 대체하지 않는다. 공개할 코드의 팀 권리와 학교 규정을 확인한다. 브랜치 빌드와 PR 절차는 [CONTRIBUTING](../../CONTRIBUTING.md#작업-흐름)을 따른다.
