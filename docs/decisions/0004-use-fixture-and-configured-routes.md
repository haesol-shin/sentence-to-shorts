# 0004 fixture adapter와 설정 기반 세부 라우팅을 제안한다

## Status

Proposed

## Date

2026-11-14

## Context

병렬 구현과 CI에는 외부 인증 없이 같은 응답을 재현하는 경로가 필요하다. 작업별 세부 모델 배정은 아직 제품 결정이 아니다.

## Decision

`fixture` adapter가 고정 입력에 대응하는 시험 응답을 반환하도록 제안한다. 일치하는 응답이 없으면 실패하도록 제안한다. provider 구현은 `anthropic_api`, `openai_compat`, `claude_cli`, `fixture`로 분리하도록 제안한다. 라우팅과 effort는 `core/config/models.yaml` 한 곳에 두도록 제안한다. 단순 장면 데이터에는 Haiku 계열을 배정하도록 제안한다. 새 코드와 장면 재작성에는 상위 모델을 배정하도록 제안한다. 정확한 ID와 effort는 공식 지원 범위를 확인한 뒤 시험으로 정한다.

## Basis

- [Anthropic effort 문서](https://platform.claude.com/docs/en/build-with-claude/effort)는 작업에 맞춘 effort 조정을 설명한다.
- [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat)는 호환 adapter의 요청 기준이다.
- Team decision: provider 교체와 모델 라우팅을 지원한다. fixture와 세부 배정의 승인은 뜻하지 않는다.

## Considered options

- 고정 fixture와 설정 기반 라우팅: 재현 가능한 구현 경로로 제안한다.
- 모든 CI에서 실제 API 호출: 인증과 사용량에 의존해 선택하지 않는다.
- 함수마다 model 하드코딩: 배정 변경이 흩어져 선택하지 않는다.

## Consequences

- fixture 성공을 실제 provider 성공으로 보고하면 안 된다.
- 라우팅 변경은 품질과 사용량을 함께 비교해야 한다.
- 실제 provider 수락 시험은 별도로 필요하다.
