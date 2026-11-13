# 0001 ADR로 결정과 근거를 기록한다

## Status

Accepted

## Date

2026-11-14

## Context

결정의 이유만으로는 선택의 출처를 확인할 수 없다. 공개 문서는 개인 대화와 내부 자료를 노출하지 않아야 한다.

## Decision

의미 있는 결정마다 ADR 하나를 작성한다. 작은 결정은 같은 문제를 다룰 때만 묶는다. 파일명은 `NNNN-kebab-title.md`로 쓴다. 각 기록은 Status, Date, Context, Decision, Basis, Considered options, Consequences를 갖는다. 확정 결정에는 Accepted를 쓴다. 검토 중인 안에는 Proposed를 쓴다. 결정을 바꾸는 작업은 새 ADR을 추가한다. 새 ADR은 대체하는 ADR에 링크한다.

## Basis

- Team decision: ADR로 결정과 근거를 관리한다.
- [MADR 공식 안내](https://adr.github.io/madr/)는 결정별 기록과 연속 번호 파일명을 안내한다.
- [MADR 4.0.0 minimal template](https://github.com/adr/madr/blob/4.0.0/template/adr-template-minimal.md)의 맥락, 대안, 결정, 결과 구조를 사용한다. Status, Date, Basis는 프로젝트 요구에 맞춰 추가한다.

## Considered options

- ADR: 결정별 출처와 대안을 남길 수 있어 선택한다.
- SPEC 안의 이유 문장만 유지: 결정 변경 이력을 찾기 어려워 선택하지 않는다.
- 개인 대화 공개: 공개 문서의 범위를 벗어나 선택하지 않는다.

## Consequences

- 결정의 근거를 코드 변경과 함께 검토할 수 있다.
- 새 결정과 기존 결정의 변경을 문서 작업에 포함해야 한다.
- 공개 기록에는 Team decision 또는 공식 문서 링크만 근거로 넣는다.
