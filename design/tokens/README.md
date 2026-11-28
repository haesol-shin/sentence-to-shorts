# 디자인 token

`tokens.json`이 디자인 값의 유일한 원본이고 나머지는 여기서 만든다. 부품과 앱 화면은 `frontend/src/shared/ui/tokens.css` 한 파일을 읽고 그 안의 역할 token만 쓴다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `tokens.json` | 값의 유일한 원본. 색 두 층, 글자, 간격, 크기, 반경, 그림자, 겹침 순서, 포커스, 아이콘, 움직임, 대비 예외, 상태 행렬과 상태 색표, 글꼴 기록 |
| `build.mjs` | 원본에서 `frontend/src/shared/ui/tokens.css`와 아래 두 표를 만든다 |
| `shell.css` | 손으로 지키는 shell 이름과 배치 값. 생성기가 만든 CSS 안에 그대로 넣는다 |
| `frontend/src/shared/ui/tokens.css` | 만든 CSS 변수. 부품과 앱 화면이 함께 읽는다. 직접 고치지 않는다 |
| `contrast.md` | 만든 대비 표. 글자와 바탕의 모든 조합, 그림 위의 면, 포커스 표시와 아이콘, 금지 목록 |
| `states.md` | 만든 상태 행렬, 상태 색표, 조합 색표 |
| `fonts/` | Pretendard 정적 파일 400과 700, SIL OFL 1.1 원문 |
| `tests/` | 수락 시험. 만든 파일, 대비, 상태표, 글꼴 해시, shell 별칭을 확인한다 |

## 명령

저장소 root에서 실행한다.

```sh
node design/tokens/build.mjs
node design/tokens/build.mjs --check
cd frontend && npx vitest run --root ../design/tokens --environment node
```

`check_fast.py`는 이 시험을 돌리지 않는다. PR CI의 visual job이 같은 명령과 `--check`를 돌린다.

디자인 값은 `tokens.json`만, shell 이름과 배치 값은 `shell.css`만 고치고 `build.mjs`를 실행한다. 만든 파일은 직접 고치지 않는다. `--check`는 만든 파일이 두 원본과 같은지만 본다.

## 색 두 층

`--palette-*`는 실제 색 값이고 `--*` 역할 token은 팔레트만 가리킨다. 역할 이름은 shadcn/ui의 CSS 변수 이름을 따른다: `--background`, `--foreground`, `--card`, `--popover`, `--primary`, `--secondary`, `--muted`, `--accent`, `--destructive`, `--border`, `--input`, `--ring`과 각 짝의 `-foreground`.

shadcn/ui 이름에 없는 역할은 아래와 같다. 값은 모두 결정표의 색이다.

- `--primary-hover`: 대표색 단추의 올림 면이다. 시안 값 #34383C를 팔레트 `gray-12`로 두고 가리킨다.
- `--primary-pressed`와 `--accent-pressed`: 표에 있는 눌린 면 두 값을 눌림 상태에 쓴다.
- `--state-hover-white`, `--state-selected`, `--state-pressed-white`: 흰 면 위 부품의 올림 #F2F4F6, 선택 #E5E8EB, 눌림 #DADDE1 면이다.
- `--state-hover-gray`, `--state-pressed-gray`: 회색 바탕 부품(보조 단추 등)의 올림·눌림 면이다.
- `--sub`: 보조 글자 #646B76. 회색 면 `--muted`에서 4.88로 4.5를 넘고, 값 칸의 자리표시 글자에 쓴다.
- `--emphasis`: 강조 단어와 안 본 변경 표시, 진행 표시의 spinner와 아이콘에 쓰는 파랑이다. 포커스 선 `--ring`은 정한 파랑 `blue` #3182F6을 쓰고, 회색 올림 면의 3:1 미달은 `contrast.exceptions`에 감수로 적는다.
- `--progress`: 진행 글자와 그 안의 숫자에 쓰는 파랑 #1B64DA다. 흰 면 5.41, 회색 면 4.62로 4.5를 넘고 진한 면에는 쓰지 않는다. spinner와 아이콘은 `--emphasis`를 쓴다.
- `--disabled-foreground`: 쓸 수 없는 글자 색이다.
- `--overlay-*` 다섯 가지: 그림 위에 놓는 반투명 면이다. `--overlay-dialog-scrim`은 확인 창 뒤의 진한 회색 24% 막이고 나머지 네 가지는 흰 막과 그림 위 표시다.

성공 상태 색은 결정표에 값이 없어 만들지 않았다. 지금 상태 목록도 성공 색을 쓰지 않는다.

`--palette-gray-1`과 `--palette-blue-light`은 지금 역할이 없다. 팔레트는 정한 색의 목록이고 역할은 쓰는 곳이 생길 때 붙인다.

## 작은 글자 규칙

모든 글자 크기가 24px 아래이므로 글자 조합은 4.5:1을 넘어야 한다. 계산 결과가 표를 정한다.

- 뜻 색(`--muted-foreground`, `--destructive`, `--warning`, `--emphasis`)을 작은 글자로 쓰는 면은 `contrast.md`가 정한다. 요소 면 `--card` #F2F4F6에서 `--muted-foreground`는 4.88, `--warning`은 4.55로 통과하고 `--destructive`는 4.38, `--emphasis`는 3.37을 감수한다. `--sub`는 같은 면에서 4.88로 통과해 값 칸의 자리표시 글자에 쓴다.
- 회색 면과 강조 면 위의 글자는 `--foreground`를 쓴다. 이 조합은 11을 넘는다.
- 꼬리표와 안내 문장은 결정표대로 회색 바탕(`--muted`)을 쓴다. 그 바탕의 뜻 색 글자는 `--muted-foreground` 4.88, `--warning` 4.55가 통과하고 `--destructive`는 4.38, `--emphasis`는 3.37로 미달이다. 그래서 `--emphasis`는 아이콘에 쓰거나 밝은 면으로 옮긴다.
- 강조 단어의 작은 파랑 글자(`--emphasis`)는 `--card`에서 3.37, `--popover`에서 3.71이고, 정한 오류 빨강(`--destructive`)은 `--card`, `--secondary`, `--muted`에서 4.38이고, 길이 표시 막(`--overlay-length`) 위 `--card`는 4.30이다. 이 조합들을 감수한다. 진행 글자는 `--progress`를 써서 흰 면 5.41로 4.5를 넘긴다.
- 쓸 수 없는 글자는 WCAG 예외로 두고 `contrast.md`에 따로 적는다.

## 상태

`states.md`의 상태 행렬이 부품마다 받는 상태, 함께 켜지는 조합, 우선순위를 정한다. 상태 색표는 상태마다, 조합 색표는 함께 켜지는 상태마다 바탕, 글자, 아이콘, 테두리를 역할 token으로 적는다. 조합에서 같은 칸을 두 상태가 다투면 우선순위가 높은 상태가 이긴다. 표에 없는 조합은 쓰지 않는다.

## shell 이름

`shell.css`는 앱 shell이 아직 읽는 이름(`--surface`, `--text`, `--line`, `--radius-card`, `--layout-*`)을 역할 token에 잇는다. 색 값을 다시 적지 않고 `var(--card)`처럼 역할만 가리키므로 화면 색의 원본은 `tokens.json` 하나다. 배치 값(`--layout-*`, `--touch-target`)은 이 앱의 측정값이라 여기에 손으로 둔다. 화면 작업이 화면을 역할 이름으로 옮기면 그때 별칭을 지운다.

## 직접 색 금지

부품과 화면은 `--palette-*` 이름이나 hex, rgb, hsl 같은 색 값을 직접 쓰지 않고 역할 token만 쓴다. 시험이 `frontend/src/components/`와 `frontend/src/gallery/`의 `.ts`, `.tsx`, `.css`에서 팔레트 이름과 색 값을 찾는다. 값의 원본인 `frontend/src/shared/ui/tokens.css`는 그 두 폴더 밖이라 검사 대상이 아니다. 이 규칙을 ESLint나 stylelint로 옮기려면 `frontend/eslint.config.js`를 고쳐야 하고, 그전까지는 시험이 같은 자리를 맡는다.

## 글자

Pretendard 정적 파일 두 개(400, 700)를 동봉하고 외부 CDN을 쓰지 않는다. 굵기는 둘뿐이다. 먼저 Pretendard를 쓰고 없으면 system-ui, 그다음 일반 산세리프를 쓴다. 크기와 줄 높이는 큰 문장 34/46, 제목 22/30, 본문 17/26, 보조 15/22이고 그림 위 장면 번호 13, 그림 위 길이 표시 12는 크기만 둔다. `tokens.json`의 `fonts`가 파일 경로와 SHA-256과 라이선스를 기록하고 시험이 파일 해시를 견준다.

`@font-face`의 파일 경로는 CSS 파일 위치를 기준으로 만든다. 만든 파일은 `frontend/src/shared/ui/tokens.css` 하나이고 `../../../../design/tokens/fonts/`를 가리킨다. 글꼴을 옮기면 다시 만든다.

## 반경

반경은 부품 묶음마다 하나다.

| token | 값 | 쓰는 곳 |
| --- | --- | --- |
| `--radius-column` | 36px | 대화 칸, 작업 칸 |
| `--radius-composer` | 28px | 대화 입력창 |
| `--radius-surface` | 24px | 메뉴, 창, 판, 끌어다 놓는 칸 |
| `--radius-toast` | 22px | 알림 |
| `--radius-row` | 18px | 메뉴와 목록의 줄 |
| `--radius-content` | 16px | 안내 문장, 파일 칩, 대사 줄, 두 줄 이상 tooltip |
| `--radius-media` | 12px | 편집 미리보기, 장면 썸네일, 카드 그림, 진행 막대 |
| `--radius-inset` | 8px | 칩 속 그림 |
| `--radius-pill` | 999px | 원 단추, 알약 단추, 꼬리표, 한 줄 tooltip |
| `--radius-none` | 0 | 전체 영상 플레이어 |

## 크기

| token | 값 | 쓰는 곳 |
| --- | --- | --- |
| `--size-control` | 44px | 모든 조작의 기본 높이와 누를 영역 |
| `--size-dialog` | 480px | 확인 창 너비 |

## 겹침 순서

`--z-tooltip` 20, `--z-picker` 30, `--z-menu` 40, `--z-panel` 45, `--z-card-over-panel` 50, `--z-toast` 60, `--z-description` 70, `--z-dialog` 90, `--z-file-drop` 95다.

바탕 면과 고정된 상단바와 사이드바는 z-index를 쓰지 않는다. 상단바와 사이드바는 sticky나 fixed로 두어 스크롤하는 내용 위에 그려지고, 겹치는 면은 모두 이 아홉 단계 안에서 연다. 떠 있는 면 하나가 하나의 겹침 문맥이 된다. 창이나 판 안에서 연 메뉴와 tooltip은 그 창의 문맥 안에서 같은 token을 쓰므로 창보다 위에 그려진다. 부품은 숫자를 직접 쓰지 않고 `--z-*`만 쓴다.

## 포커스와 아이콘

포커스는 `--ring` 2px이고 바깥 간격은 기본 2px, 메뉴와 목록의 줄은 안쪽 -2px, 그림 카드는 바깥 6px이다. 키보드로 왔을 때만 보인다. 포커스 선이 보이는 동안 누름 바탕은 칠하지 않는다. 안쪽 선을 쓰는 줄에서 파랑이 눌린 면과 2.73:1이라 3:1을 넘지 못하기 때문이다.

아이콘 크기는 14(칩 안 닫기), 16(줄 안 재생, 도움말), 20(기본), 22(제목 옆), 32(그림 자리표시)이고 선 두께는 2px다. 채운 아이콘이 기본이고 선 아이콘은 채운 짝이 없는 조작 기호와 사이드바에만 쓴다.

## 움직임

세 종류다. 상태 변화 120ms, 판 열고 닫기 200ms, 화면 전환 0ms다. 미리보기 바탕이 바뀔 때만 240ms를 쓴다. easing은 모두 `ease`다. `prefers-reduced-motion: reduce`에서 네 길이를 모두 0ms로 바꾸며 이 처리는 `tokens.css` 한 곳에 있다.

## 다크 모드

만들지 않았다. 같은 역할 이름을 `.dark` 선택자로 덮어쓸 자리만 CSS 주석으로 두었다. 지금 값은 밝은 테마 하나뿐이다.

## 결정표에 없는 값

아래 값은 결정표에 없어 만들지 않았다. 필요한 화면이 생기면 값을 먼저 정한다.

- 성공 상태 색과 다크 모드 색.
- 켜기와 끄기의 스위치 손잡이 색. 지금은 켜짐이 회색 바탕으로 남는 단추 모양이다.
- 회색 바탕에 뜻 색 글자를 쓰는 조합. `--warning`만 4.55로 통과하고 나머지는 글자를 `--foreground`로 두고 뜻 색을 아이콘에만 쓴다.
