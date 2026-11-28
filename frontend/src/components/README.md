# 공통 부품

부품마다 `frontend/src/components/<Name>/`에 React 컴포넌트와 CSS와 시험을 둔다. 공통 크기와 투명 누를 영역은 `base.css` 한 곳에 있고, 색과 글자와 간격은 `frontend/src/shared/ui/tokens.css`의 역할 token만 쓴다.

## 규칙

- `forceState`는 갤러리의 시각 상태 강제에만 쓴다. 실제 상호작용은 `:hover`, `:active`, `:focus-visible`과 Base UI의 열림 속성이 맡는다.
- 보이는 크기는 결정값 그대로 두고 `.hit-area::after`가 44x44를 채운다. 이 계산은 부품마다 하지 않는다.
- 다른 부품이 필요한 자리는 호출자가 합성한다(MenuButton의 trigger, Chip의 remove, SettingsRow의 control). 그래야 한 역할에 한 부품만 남는다.
- 부품은 화면 읽기용 이름과 상태 글을 고정한 한국어로 두지 않는다. 호출자가 prop으로 넘기고, 한국어 문구는 갤러리가 값으로만 준다. 항목마다 이름이 갈리는 조작(ReorderList의 이동 단추)은 항목 이름을 받아 이름을 돌려주는 함수를 받는다.
- trigger로 쓰는 단추는 `React.forwardRef`로 ref를 DOM까지 넘긴다. React 18에서 이것이 없으면 tooltip과 메뉴 열림 상태가 깨진다.
- `frontend/src/shared/ui/tokens.css`는 `design/tokens/tokens.json`과 `design/tokens/shell.css`에서 만든 파일이다. 직접 고치지 않는다.

## 반원 부품의 안쪽 여백

반원(`--radius-pill`)과 그에 준하는 부품은 바깥 가장자리에서 첫 표시까지의 안쪽 여백을 양쪽에서 같게 둔다. 글자와 아이콘이 함께 있는 부품은 그 값을 높이의 절반으로 두어 반원이 끝나는 자리에서 내용이 시작한다(기준: 값 칸의 아이콘 쪽). 아이콘 상자에는 안쪽 빈 공간이 있어서 끝에 놓인 아이콘은 `base.css`의 `--icon-ink-glyph`(화살표, 닫기)와 `--icon-ink-mark`(원, 체크, 파일)만큼 바깥으로 당겨 아이콘의 선이 그 자리에 오게 한다. spinner처럼 상자 끝에서 그려지는 표시는 당기지 않는다.

글자와 아이콘이 함께 있는 적용 부품: Button(md 44, sm 32, trigger), Chip(닫기 단추 쪽 포함), Tag, RadioGroup의 선택 항목, ValueField의 값 칸, TextField, SettingsRow의 값 칸, TopBarItem과 TopBarStatus의 trigger, Composer의 값 칩(Button sm을 36으로 키운 것). 글자만 있는 반원(StageIndicator의 단계)은 양쪽 여백이 이미 같아 그대로 두고, 아이콘 하나만 있는 부품(IconButton, CloseButton, SidebarItem, PlaybackControls, SendButton, ReorderList의 이동 단추)과 작은 겹침 칩(Card의 번호와 길이), popup 면(Tooltip, MenuButton의 메뉴)은 상자 가운데 정렬이라 이 규칙에 넣지 않는다. 새 반원 부품은 이 목록과 `frontend/tests/gallery/pill-parts.spec.ts`의 부품 목록에 함께 더한다.

## 호버 색

흰 면 위 부품의 호버는 `--state-hover-white`, 회색 면 위 부품의 호버는 `--state-hover-gray`를 쓴다. 한 면의 부품은 같은 역할 token을 쓴다.

## 단추 줄 순서

두 개 이상의 단추가 한 줄에 서면 회색 단추(secondary, ghost)가 먼저 오고 검정 단추(primary)가 마지막에 온다. 줄을 그리는 부품이 이 순서를 정하고 호출자는 그 순서대로 단추를 넘긴다. `ConfirmDialog`와 `RangeDialog`는 취소를 먼저, 확인을 마지막에 그린다.

## 시험

- 부품 시험은 각 부품 폴더의 `*.test.tsx`에 있고 `npx vitest run src/components`로 돈다.
- 갤러리 상태 목록 시험과 화면 캡처와 누를 영역 측정은 `frontend/tests/gallery/`에 있다.
