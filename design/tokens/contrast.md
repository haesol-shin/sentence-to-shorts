# 대비

`tokens.json`에서 만든 문서다. 값을 고치고 `node design/tokens/build.mjs`를 실행해 다시 만든다. 이 파일은 직접 고치지 않는다.

## 글자와 바탕

작은 글자는 4.5:1 이상이어야 한다. 이 제품의 글자 크기는 12px에서 22px까지이고 큰 문장 34px만 24px를 넘으므로 모든 조합을 4.5:1로 본다. 판정이 금지인 조합은 쓰지 않는다.

| 글자 | 바탕 | 대비 | 판정 |
| --- | --- | --- | --- |
| `--foreground` | `--background` | 12.99 | 통과 |
| `--foreground` | `--card` | 15.22 | 통과 |
| `--foreground` | `--popover` | 15.22 | 통과 |
| `--foreground` | `--primary` | 1.00 | 금지 |
| `--foreground` | `--primary-pressed` | 1.43 | 금지 |
| `--foreground` | `--secondary` | 13.80 | 통과 |
| `--foreground` | `--muted` | 13.80 | 통과 |
| `--foreground` | `--accent` | 12.37 | 통과 |
| `--foreground` | `--accent-pressed` | 11.17 | 통과 |
| `--card-foreground` | `--background` | 12.99 | 통과 |
| `--card-foreground` | `--card` | 15.22 | 통과 |
| `--card-foreground` | `--popover` | 15.22 | 통과 |
| `--card-foreground` | `--primary` | 1.00 | 금지 |
| `--card-foreground` | `--primary-pressed` | 1.43 | 금지 |
| `--card-foreground` | `--secondary` | 13.80 | 통과 |
| `--card-foreground` | `--muted` | 13.80 | 통과 |
| `--card-foreground` | `--accent` | 12.37 | 통과 |
| `--card-foreground` | `--accent-pressed` | 11.17 | 통과 |
| `--popover-foreground` | `--background` | 12.99 | 통과 |
| `--popover-foreground` | `--card` | 15.22 | 통과 |
| `--popover-foreground` | `--popover` | 15.22 | 통과 |
| `--popover-foreground` | `--primary` | 1.00 | 금지 |
| `--popover-foreground` | `--primary-pressed` | 1.43 | 금지 |
| `--popover-foreground` | `--secondary` | 13.80 | 통과 |
| `--popover-foreground` | `--muted` | 13.80 | 통과 |
| `--popover-foreground` | `--accent` | 12.37 | 통과 |
| `--popover-foreground` | `--accent-pressed` | 11.17 | 통과 |
| `--primary-foreground` | `--background` | 1.17 | 금지 |
| `--primary-foreground` | `--card` | 1.00 | 금지 |
| `--primary-foreground` | `--popover` | 1.00 | 금지 |
| `--primary-foreground` | `--primary` | 15.22 | 통과 |
| `--primary-foreground` | `--primary-pressed` | 10.61 | 통과 |
| `--primary-foreground` | `--secondary` | 1.10 | 금지 |
| `--primary-foreground` | `--muted` | 1.10 | 금지 |
| `--primary-foreground` | `--accent` | 1.23 | 금지 |
| `--primary-foreground` | `--accent-pressed` | 1.36 | 금지 |
| `--secondary-foreground` | `--background` | 12.99 | 통과 |
| `--secondary-foreground` | `--card` | 15.22 | 통과 |
| `--secondary-foreground` | `--popover` | 15.22 | 통과 |
| `--secondary-foreground` | `--primary` | 1.00 | 금지 |
| `--secondary-foreground` | `--primary-pressed` | 1.43 | 금지 |
| `--secondary-foreground` | `--secondary` | 13.80 | 통과 |
| `--secondary-foreground` | `--muted` | 13.80 | 통과 |
| `--secondary-foreground` | `--accent` | 12.37 | 통과 |
| `--secondary-foreground` | `--accent-pressed` | 11.17 | 통과 |
| `--muted-foreground` | `--background` | 4.13 | 금지 |
| `--muted-foreground` | `--card` | 4.83 | 통과 |
| `--muted-foreground` | `--popover` | 4.83 | 통과 |
| `--muted-foreground` | `--primary` | 3.15 | 금지 |
| `--muted-foreground` | `--primary-pressed` | 2.19 | 금지 |
| `--muted-foreground` | `--secondary` | 4.38 | 금지 |
| `--muted-foreground` | `--muted` | 4.38 | 금지 |
| `--muted-foreground` | `--accent` | 3.93 | 금지 |
| `--muted-foreground` | `--accent-pressed` | 3.55 | 금지 |
| `--accent-foreground` | `--background` | 12.99 | 통과 |
| `--accent-foreground` | `--card` | 15.22 | 통과 |
| `--accent-foreground` | `--popover` | 15.22 | 통과 |
| `--accent-foreground` | `--primary` | 1.00 | 금지 |
| `--accent-foreground` | `--primary-pressed` | 1.43 | 금지 |
| `--accent-foreground` | `--secondary` | 13.80 | 통과 |
| `--accent-foreground` | `--muted` | 13.80 | 통과 |
| `--accent-foreground` | `--accent` | 12.37 | 통과 |
| `--accent-foreground` | `--accent-pressed` | 11.17 | 통과 |
| `--destructive` | `--background` | 4.12 | 금지 |
| `--destructive` | `--card` | 4.83 | 통과 |
| `--destructive` | `--popover` | 4.83 | 통과 |
| `--destructive` | `--primary` | 3.15 | 금지 |
| `--destructive` | `--primary-pressed` | 2.20 | 금지 |
| `--destructive` | `--secondary` | 4.38 | 금지 |
| `--destructive` | `--muted` | 4.38 | 금지 |
| `--destructive` | `--accent` | 3.93 | 금지 |
| `--destructive` | `--accent-pressed` | 3.54 | 금지 |
| `--warning` | `--background` | 4.29 | 금지 |
| `--warning` | `--card` | 5.02 | 통과 |
| `--warning` | `--popover` | 5.02 | 통과 |
| `--warning` | `--primary` | 3.03 | 금지 |
| `--warning` | `--primary-pressed` | 2.11 | 금지 |
| `--warning` | `--secondary` | 4.55 | 통과 |
| `--warning` | `--muted` | 4.55 | 통과 |
| `--warning` | `--accent` | 4.08 | 금지 |
| `--warning` | `--accent-pressed` | 3.69 | 금지 |
| `--emphasis` | `--background` | 3.17 | 금지 |
| `--emphasis` | `--card` | 3.71 | 감수 |
| `--emphasis` | `--popover` | 3.71 | 감수 |
| `--emphasis` | `--primary` | 4.10 | 금지 |
| `--emphasis` | `--primary-pressed` | 2.86 | 금지 |
| `--emphasis` | `--secondary` | 3.37 | 금지 |
| `--emphasis` | `--muted` | 3.37 | 금지 |
| `--emphasis` | `--accent` | 3.02 | 금지 |
| `--emphasis` | `--accent-pressed` | 2.73 | 금지 |
| `--disabled-foreground` | `--background` | 2.25 | WCAG 예외 |
| `--disabled-foreground` | `--card` | 2.64 | WCAG 예외 |
| `--disabled-foreground` | `--popover` | 2.64 | WCAG 예외 |
| `--disabled-foreground` | `--primary` | 5.77 | WCAG 예외 |
| `--disabled-foreground` | `--primary-pressed` | 4.03 | WCAG 예외 |
| `--disabled-foreground` | `--secondary` | 2.39 | WCAG 예외 |
| `--disabled-foreground` | `--muted` | 2.39 | WCAG 예외 |
| `--disabled-foreground` | `--accent` | 2.14 | WCAG 예외 |
| `--disabled-foreground` | `--accent-pressed` | 1.93 | WCAG 예외 |

## 그림 위의 반투명 면

반투명 면은 그림 위에 놓이므로 검은 그림 픽셀과 흰 그림 픽셀 위에서 계산하고 낮은 값을 쓴다.

| 글자 | 바탕 | 대비 | 판정 |
| --- | --- | --- | --- |
| `--foreground` | `--overlay-caption` | 11.53 | 통과 |
| `--foreground` | `--overlay-scene-number` | 12.76 | 통과 |
| `--card` | `--overlay-length` | 4.74 | 통과 |
| `--foreground` | `--overlay-scrim` | 4.52 | 통과 |

## 의미 있는 아이콘과 포커스 표시 (3:1)

### 포커스 표시

포커스 표시는 그 표시가 그려지는 면과 견준다. 안쪽 선은 부품의 바탕과, 바깥 선은 부품을 둘러싼 부모 면과 견준다.

| 표시 | 이웃한 면 | 대비 | 판정 |
| --- | --- | --- | --- |
| `--ring` | `--background` | 3.17 | 통과 |
| `--ring` | `--card` | 3.71 | 통과 |
| `--ring` | `--popover` | 3.71 | 통과 |
| `--ring` | `--muted` | 3.37 | 통과 |
| `--ring` | `--accent` | 3.02 | 통과 |

### 아이콘

부품의 상태 색표에 적힌 아이콘 색은 모두 이 표 안에 있어야 한다.

| 아이콘 | 면 | 대비 | 판정 |
| --- | --- | --- | --- |
| `--foreground` | `--background` | 12.99 | 통과 |
| `--foreground` | `--card` | 15.22 | 통과 |
| `--foreground` | `--popover` | 15.22 | 통과 |
| `--foreground` | `--secondary` | 13.80 | 통과 |
| `--foreground` | `--muted` | 13.80 | 통과 |
| `--foreground` | `--accent` | 12.37 | 통과 |
| `--muted-foreground` | `--background` | 4.13 | 통과 |
| `--muted-foreground` | `--card` | 4.83 | 통과 |
| `--muted-foreground` | `--popover` | 4.83 | 통과 |
| `--muted-foreground` | `--secondary` | 4.38 | 통과 |
| `--muted-foreground` | `--muted` | 4.38 | 통과 |
| `--muted-foreground` | `--accent` | 3.93 | 통과 |
| `--emphasis` | `--card` | 3.71 | 통과 |
| `--emphasis` | `--popover` | 3.71 | 통과 |
| `--emphasis` | `--muted` | 3.37 | 통과 |
| `--warning` | `--card` | 5.02 | 통과 |
| `--warning` | `--popover` | 5.02 | 통과 |
| `--warning` | `--muted` | 4.55 | 통과 |
| `--destructive` | `--card` | 4.83 | 통과 |
| `--destructive` | `--popover` | 4.83 | 통과 |
| `--destructive` | `--muted` | 4.38 | 통과 |
| `--primary-foreground` | `--primary` | 15.22 | 통과 |
| `--primary-foreground` | `--primary-pressed` | 10.61 | 통과 |

## 감수한 조합

작은 파랑 글자는 진한 변형을 만들지 않고 흰 면에 그대로 쓴다. 이 조합만 4.5:1 아래를 감수한다.

- `--emphasis` on `--card`: 3.71
- `--emphasis` on `--popover`: 3.71

## WCAG 예외

쓸 수 없는 부품의 글자는 WCAG 대비 기준에서 제외한다.

- `--disabled-foreground` on `--background`: 2.25
- `--disabled-foreground` on `--card`: 2.64
- `--disabled-foreground` on `--popover`: 2.64
- `--disabled-foreground` on `--primary`: 5.77
- `--disabled-foreground` on `--primary-pressed`: 4.03
- `--disabled-foreground` on `--secondary`: 2.39
- `--disabled-foreground` on `--muted`: 2.39
- `--disabled-foreground` on `--accent`: 2.14
- `--disabled-foreground` on `--accent-pressed`: 1.93

## 금지 목록

여기 적힌 조합은 4.5:1 아래이고 글자에 쓰지 않는다.

- `--foreground`: `--primary` (1.00), `--primary-pressed` (1.43)
- `--card-foreground`: `--primary` (1.00), `--primary-pressed` (1.43)
- `--popover-foreground`: `--primary` (1.00), `--primary-pressed` (1.43)
- `--primary-foreground`: `--background` (1.17), `--card` (1.00), `--popover` (1.00), `--secondary` (1.10), `--muted` (1.10), `--accent` (1.23), `--accent-pressed` (1.36)
- `--secondary-foreground`: `--primary` (1.00), `--primary-pressed` (1.43)
- `--muted-foreground`: `--background` (4.13), `--primary` (3.15), `--primary-pressed` (2.19), `--secondary` (4.38), `--muted` (4.38), `--accent` (3.93), `--accent-pressed` (3.55)
- `--accent-foreground`: `--primary` (1.00), `--primary-pressed` (1.43)
- `--destructive`: `--background` (4.12), `--primary` (3.15), `--primary-pressed` (2.20), `--secondary` (4.38), `--muted` (4.38), `--accent` (3.93), `--accent-pressed` (3.54)
- `--warning`: `--background` (4.29), `--primary` (3.03), `--primary-pressed` (2.11), `--accent` (4.08), `--accent-pressed` (3.69)
- `--emphasis`: `--background` (3.17), `--primary` (4.10), `--primary-pressed` (2.86), `--secondary` (3.37), `--muted` (3.37), `--accent` (3.02), `--accent-pressed` (2.73)
