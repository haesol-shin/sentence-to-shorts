# 0008 TTS는 비교 음성을 듣고 선택한다

## Status

Accepted

## Date

2026-11-14

## Context

모델 크기와 속도만으로 음성의 자연스러움을 판단할 수 없다. 제품에는 선택한 엔진 하나만 넣어야 한다.

## Decision

Qwen3-TTS 0.6B와 Qwen3-TTS 1.7B를 시험한다. MOSS-TTS-Nano 100M ONNX와 Chatterbox Multilingual V3 ONNX도 시험한다. 후보마다 별도 환경을 쓴다. 같은 한국어 대본으로 음성을 만든다. RTF와 cold start와 peak RAM을 기록한다. 사용자가 비교 음성을 듣고 엔진을 선택한다. 한국어와 영어의 최종 청취 검수도 수행한다. 선택 전에는 엔진을 확정하지 않는다. 발음 수정 기능은 MVP에서 제외한다.

## Basis

- Team decision: 네 후보를 시험하고 사용자가 직접 듣고 고른다.
- Team decision: TTS 선택 기준은 자연스러움이다.
- Team decision: 제품에는 선택한 엔진 하나만 넣는다.

## Considered options

- 비교 청취와 실측: 취향과 실행 가능성을 함께 확인하므로 선택한다.
- benchmark만으로 선택: 자연스러움 기준을 대체하지 못해 선택하지 않는다.
- 여러 엔진 동봉: 제품 엔진 하나 결정과 맞지 않아 선택하지 않는다.

## Consequences

- 비교 기록에 실제 revision과 실행 설정을 남겨야 한다.
- 설치 실패도 비교 결과로 남겨야 한다.
- 전부 실패하면 TTS 미확정 문제로 보고해야 한다.
