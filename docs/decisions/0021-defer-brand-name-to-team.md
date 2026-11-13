# 0021 작업 이름은 sentence-to-shorts로 둔다

## Status

Accepted

## Date

2026-11-14

## Context

작업을 시작할 이름이 필요하다. 팀과 논의한 뒤 바꿀 수 있어야 한다.

## Decision

저장소와 서비스의 작업 이름은 `sentence-to-shorts`다. 팀과 논의한 뒤 이름을 바꿀 수 있다. 이름의 실행 값은 `core/config/brand.yaml`에서 읽는다. 표시 이름과 저장소 이름과 앱 ID의 원본은 같은 파일이다. 코드와 화면과 설치기와 문서는 이름을 그 파일에서 가져온다. 실행 값의 이름 문자열을 다른 파일에 하드코딩하지 않는다. 이 ADR의 이름은 결정 기록용 예외다. 앱 ID 변경이 저장 경로에 영향을 주면 데이터 이전을 검토한다.

## Basis

- Team decision: 저장소와 작업 이름은 `sentence-to-shorts`로 정한다.
- Team decision: 나중에 팀과 논의해 이름을 바꿀 수 있다.
- Team decision: `brand.yaml`을 이름의 단일 원본으로 둔다.

## Considered options

- 작업 이름을 선택하고 설정으로 관리: 구현과 향후 이름 변경을 함께 지원하므로 선택한다.
- 최종 이름으로 고정: 팀 논의 뒤 바꿀 수 있어야 하므로 선택하지 않는다.
- 이름을 여러 파일에 복사: 변경이 흩어져 선택하지 않는다.

## Consequences

- 이 ADR의 이름은 결정 기록이다.
- 실행 설정의 원본은 `brand.yaml` 하나다.
- 이름 변경 시 GitHub 저장소 rename과 설정 변경을 함께 확인해야 한다.
- brand 검사는 이 결정 기록만 명시적으로 허용한다.
- 다른 문서의 이름 하드코딩은 계속 검사한다.
