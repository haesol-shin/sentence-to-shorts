# 0022 작은 fixture 묶음으로 prompt 문체를 검토한다

## Status

Proposed

## Date

2026-11-14

## Context

[ADR 0018](0018-store-prompts-as-files.md)은 prompt 파일 배치와 검증을 제안한다. schema 검사만으로는 말투와 어휘와 읽기 자연스러움을 확인할 수 없다. 문체 검토가 새 빌드 gate가 되지 않도록 작은 비교 자료가 필요하다.

## Decision

문체와 검토 방식의 실행 원본은 [CONTRACTS §10.5](../CONTRACTS.md#105-prompt-문체와-작은-검토)로 제안한다. 각 route 파일에 짧은 `style notes`를 둔다. 목표 말투의 짧은 예시를 1~2개 둔다. 별도 검토 입력은 route마다 2~5개 둔다. 같은 입력의 변경 전후 응답을 한 HTML 페이지에 나란히 표시한다. 실제 모델 응답이 없으면 품질 미검증으로 표시한다. 선택 lint는 작성자가 로컬에서 수동 실행한다. 부정 지시와 all-caps 후보는 경고만 한다. 변경 전후 비교 페이지도 로컬에서만 만든다. 문체 lint와 문체 검토는 CI에서 실행하지 않는다. CI의 경고 작업으로도 실행하지 않는다. 경고와 소유자 열람 대기는 병합의 새 gate로 쓰지 않는다.

지시는 원하는 동작과 그 이유로 쓴다. 한국어 대본의 prompt와 예시는 한국어로 쓴다. 선택한 register와 어조를 따른다. 강조용 all-caps 대신 보통 문장을 쓴다. 출력에 써도 되는 어휘를 고른다.

기존 tools-off 호출과 `text`·`png` 데이터 parts를 유지한다. 신뢰된 지시는 system에 둔다. 이 방식은 Anthropic의 `tool_result` 권고와 다르다. 문체 비교를 이유로 도구 교환을 도입하지 않는다.

## Basis

- [Anthropic prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)는 원하는 동작과 이유와 출력에 맞춘 prompt 문체와 예시를 권한다.
- [OpenAI prompting guide](https://developers.openai.com/api/docs/guides/prompt-engineering)는 communication style과 원하는 출력 예시를 명시하도록 권한다.
- [Anthropic indirect prompt injection 권고](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks)는 제삼자 자료를 `tool_result`로 보내도록 권한다.
- 해석·적용안: 언어와 register의 일치와 어휘 선택은 위 공식 문체 권고를 앱에 적용한 것이다. 어휘 전이는 공식 문서가 보장하는 법칙이 아니다.
- Team decision: 문체 lint는 작성자가 로컬에서 수동 실행한다. 비교 페이지도 로컬에서만 만든다. 문체 검사는 CI에서 경고로도 실행하지 않는다.
- 예시 수와 검토 입력 수와 비교 도구의 세부 구현은 이 앱의 설계 제안이다.

## Considered options

- 작은 비교 페이지: 사람이 실제 문장을 읽을 수 있어 제안한다.
- lint를 필수 CI로 적용: 문장 형태를 품질로 오인할 수 있어 선택하지 않는다.
- 새 평가 플랫폼: 작은 문체 검토에 필요한 범위를 넘어 선택하지 않는다.

## Consequences

- 비교 자료는 품질 점수나 보안 보장이 아니다.
- prompt 안 예시와 검토 입력은 분리한다.
- 합성 응답과 녹화 재생은 renderer 검증에만 쓴다.
- 실제 모델 품질은 실제 응답을 읽은 뒤에만 판단한다.
- 이 ADR은 ADR 0018을 대체하지 않는다.
