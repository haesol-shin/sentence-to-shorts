# 공통 부품

부품마다 `frontend/src/components/<Name>/`에 React 컴포넌트와 CSS와 시험을 둔다. 공통 크기와 투명 누를 영역은 `base.css` 한 곳에 있고, 색과 글자와 간격은 `frontend/src/shared/ui/tokens.css`의 역할 token만 쓴다.

## 규칙

- `forceState`는 갤러리의 시각 상태 강제에만 쓴다. 실제 상호작용은 `:hover`, `:active`, `:focus-visible`과 Base UI의 열림 속성이 맡는다.
- 보이는 크기는 결정값 그대로 두고 `.hit-area::after`가 44x44를 채운다. 이 계산은 부품마다 하지 않는다.
- 다른 부품이 필요한 자리는 호출자가 합성한다(MenuButton의 trigger, Chip의 remove, SettingsRow의 control). 그래야 한 역할에 한 부품만 남는다.
- trigger로 쓰는 단추는 `React.forwardRef`로 ref를 DOM까지 넘긴다. React 18에서 이것이 없으면 tooltip과 메뉴 열림 상태가 깨진다.
- `frontend/src/shared/ui/tokens.css`는 `design/tokens/tokens.json`과 `design/tokens/shell.css`에서 만든 파일이다. 직접 고치지 않는다.

## 시험

- 부품 시험은 각 부품 폴더의 `*.test.tsx`에 있고 `npx vitest run src/components`로 돈다.
- 갤러리 상태 목록 시험과 화면 캡처와 누를 영역 측정은 `frontend/tests/gallery/`에 있다.
