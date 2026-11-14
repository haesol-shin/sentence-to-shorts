# 0023 shadcn/ui on Base UI로 화면 부품을 만든다

이 문서는 화면 부품 기반 library의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

[ADR 0017](0017-build-react-components-with-gallery.md)의 공통 부품은 tooltip, popover, select, dialog, menu 같은 접근성 동작을 직접 만들지 않고 검증된 primitive 위에 만들어야 한다. frontend는 React 18이다([CONTRACTS 16.1](../CONTRACTS.md#161-원본과-runtime)). 같은 시험 화면에서 열림, Escape 닫힘, 포커스 복귀, 열린 trigger의 `aria-expanded`를 쟀다. shadcn/ui on Base UI와 shadcn/ui on Radix는 React 18과 19에서, React Aria Components는 React 18에서 시험했다. React 18에서는 세 후보 모두 ref를 넘기지 않는 Button을 trigger로 쓰면 일부 동작이 깨졌고, 공통 Button에 `React.forwardRef`를 넣으면 Base UI 조합은 React 19와 같게 동작했다.

## Decision

화면 부품은 [shadcn/ui](https://ui.shadcn.com/docs)의 [Base UI](https://base-ui.com/react/overview/about) 판(`components.json` style `base-nova`)으로 만든다. 부품 코드는 `shadcn add`로 저장소에 복사해 [ADR 0016](0016-use-selected-design-tokens.md) token으로 고친다. React는 18을 유지하고, trigger로 쓰는 공통 부품은 `React.forwardRef`로 ref를 넘긴다. 대표색 token 이름은 `primary`다. [shadcn theming](https://ui.shadcn.com/docs/theming)에서 `accent`는 옅은 hover 바탕을 뜻하기 때문이다. 이 ADR은 ADR 0016의 대표색 이름만 대체하고 값과 나머지 token은 그대로 둔다.

대안: React Aria Components는 접근성 문서가 가장 강하지만 조합 부품을 직접 만드는 양이 많음. Radix도 React 18에서 같은 ref 고침이 필요하고, 이번 기능 시험만으로 Base UI 선택을 바꿀 근거는 얻지 못함. React 19로 올리면 ref 고침이 필요 없지만 React 18 유지가 먼저 정해짐.

## Consequences

의존성 버전 고정과 `components.json`은 frontend 뼈대 작업이 맡는다. 갤러리 수락 시험에 개발 모드 ref 경고 0건, Select·Dialog·Popover·Menu trigger의 `aria-expanded`, 키보드·Escape·포커스 복귀를 넣는다. 시험한 부품 밖의 부품도 같은 시험을 통과해야 한다. React를 19로 올리면 이 ADR의 ref 규칙을 다시 본다.
