# 0009 업로드 BGM과 코드 BGM을 제공한다

## Status

Accepted

## Date

2026-11-14

## Context

영상의 분위기는 소리에도 영향을 받는다. 내장 곡만으로는 사용자 취향을 모두 표현할 수 없다.

## Decision

BGM은 기본으로 켠다. 영상마다 분위기에 맞춰 선택한다. 사용자 BGM 업로드를 지원한다. Python 코드로 만드는 BGM도 지원한다. 생성형 음악 모델은 쓰지 않는다. 코드 BGM은 승인된 sandbox에서 실행한다. 실행 결과는 WAV로만 받는다. 최소 구현은 짧은 loop의 생성과 저장과 미리 듣기와 재사용이다.

## Basis

- Team decision: BGM 기본 사용과 영상별 선택을 제공한다.
- Team decision: 사용자 음원 업로드와 코드 BGM을 포함한다.
- Team decision: 코드 BGM은 그림 코드와 같은 sandbox를 사용한다.

## Considered options

- 내장·업로드·코드 BGM: 서로 다른 제작 요구를 제공하므로 선택한다.
- 생성형 음악 모델: 제품 범위에서 제외한다.
- 코드 BGM을 host에서 실행: 승인된 보안 경계를 벗어나 선택하지 않는다.

## Consequences

- 부모 process에 별도 WAV 검증기가 필요하다.
- 업로드 음원의 권리는 내장 곡의 권리와 구분해야 한다.
- loop 경계와 클리핑과 음성 가림을 청취해야 한다.
