# 0018 prompt 파일 배치와 검증 방식을 제안한다

## Status

Proposed

## Date

2026-11-14

## Context

prompt의 문구는 코드 구조와 별도로 수정할 수 있어야 한다. 파일 분리의 세부 방식은 아직 정하지 않았다.

## Decision

prompt를 코드 밖 파일로 분리하는 원칙을 따른다. 구체적인 배치는 `core/prompts/`로 제안한다. 작업별 trusted 지시문과 untrusted 사용자 자료를 분리하도록 제안한다. 파일의 변수와 출력 schema와 예시를 명시하도록 제안한다. 변경할 때 같은 fixture로 품질과 출력 계약을 비교하도록 제안한다. prompt digest를 실행 기록과 cache 판정에 연결하도록 제안한다. 정확한 파일 형식과 loader는 공식 가이드 검토 뒤 정한다.

## Basis

- Team decision: prompt를 파일로 분리한다. 이 ADR의 구체적인 경로와 loader와 검증 방식의 승인은 뜻하지 않는다.
- [Anthropic prompt engineering](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview)은 prompt 작성의 공식 근거다.
- [OpenAI prompt engineering](https://platform.openai.com/docs/guides/prompt-engineering)은 지시문 구성과 평가의 공식 근거다.

## Considered options

- 작업별 파일과 명시적 입력: 문구와 실행 코드의 변경을 분리할 수 있어 제안한다.
- 코드 안에 긴 문자열 유지: 정성적 문구 수정을 어렵게 해 선택하지 않는다.
- 대화 이력을 trusted 지시문으로 사용: 사용자 자료와 실행 규칙의 경계가 흐려져 선택하지 않는다.

## Consequences

- 파일 분리 원칙은 확정됐지만 이 ADR 전체는 Proposed다.
- prompt 수정도 결과 품질과 schema 적합성을 검토해야 한다.
- 문체 비교의 작은 절차는 [ADR 0022](0022-review-prompt-style-with-small-fixtures.md)에서 추가로 제안한다.
- 문체 lint는 작성자가 로컬에서 수동 실행한다.
- 변경 전후 비교 페이지도 로컬에서만 만든다.
- 문체 검사는 CI에서 경고로도 실행하지 않는다.
- 로그에는 실제 사용자 prompt 원문을 기본 수집하지 않는다.
