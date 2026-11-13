# 0013 공개 main 중심 저장소로 운영한다

## Status

Accepted

## Date

2026-11-14

## Context

개발과 배포를 장기 브랜치로 나누면 같은 기능을 두 번 관리하게 된다. 공개 저장소는 코드 외 자산의 권리도 확인해야 한다.

## Decision

개인 GitHub의 공개 저장소로 처음부터 운영한다. 장기 브랜치는 main 하나만 둔다. 짧은 기능 브랜치에서 PR을 만든다. 미완성 기능은 PR 브랜치 빌드로 시험한다. PR은 squash로 병합한다. 커밋 제목은 영어 `type(scope): summary` 형식을 쓴다. 코드 라이선스는 Apache-2.0으로 둔다. 모델과 음원과 글꼴의 라이선스는 코드 라이선스로 대체하지 않는다.

## Basis

- Team decision: 처음부터 공개로 운영한다.
- Team decision: main 하나와 짧은 브랜치를 사용한다.
- Team decision: 배포·개발 리뷰 수정안을 반영한다.
- Team decision: 기존 `type(scope): summary` 커밋 형식을 사용한다.
- Team decision: 코드 라이선스는 Apache-2.0이다.
- [Conventional Commits 명세](https://www.conventionalcommits.org/en/v1.0.0/)는 커밋 형식의 기준이다.
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)은 코드 라이선스 원문이다.

## Considered options

- main과 짧은 PR 브랜치: 하나의 제품 코드를 유지할 수 있어 선택한다.
- 별도 dev 장기 브랜치: 사용자 결정에 따라 사용하지 않는다.
- 비공개로 개발한 뒤 공개: 처음부터 공개 운영 결정과 맞지 않아 선택하지 않는다.

## Consequences

- 공개 전부터 secret과 개인정보 노출을 막아야 한다.
- 공개할 코드의 팀 권리와 학교 규정을 확인해야 한다.
- 외부 자산의 표시 의무를 별도로 관리해야 한다.
