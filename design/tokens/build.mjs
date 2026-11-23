// Generate the token stylesheet and the two reference tables from tokens.json.
//
// tokens.json is the only source of the design values; shell.css holds this
// app's measurements and the names the screens still read. Run
// `node design/tokens/build.mjs` after editing either; `--check` compares the
// outputs with what the sources would generate.

import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const TOKEN_DIR = dirname(fileURLToPath(import.meta.url));
export const TOKENS_PATH = join(TOKEN_DIR, 'tokens.json');
export const FONT_DIR = join(TOKEN_DIR, 'fonts');
export const SHELL_PATH = join(TOKEN_DIR, 'shell.css');

export const OUTPUTS = {
  css: join(TOKEN_DIR, '..', '..', 'frontend', 'src', 'shared', 'ui', 'tokens.css'),
  contrast: join(TOKEN_DIR, 'contrast.md'),
  states: join(TOKEN_DIR, 'states.md'),
};

export function loadTokens() {
  return JSON.parse(readFileSync(TOKENS_PATH, 'utf8'));
}

// ---- color ----

export function parseColor(value) {
  const hex = /^#([0-9a-f]{6})$/i.exec(value);
  if (hex) {
    const n = Number.parseInt(hex[1], 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255, a: 1 };
  }
  const rgba = /^rgba\((\d+), (\d+), (\d+), ([0-9.]+)\)$/.exec(value);
  if (rgba) {
    return { r: Number(rgba[1]), g: Number(rgba[2]), b: Number(rgba[3]), a: Number(rgba[4]) };
  }
  throw new Error(`unsupported color value: ${value}`);
}

function channel(value) {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance({ r, g, b }) {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function ratio(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

function over(color, backdrop) {
  const mix = (front, back) => Math.round(color.a * front + (1 - color.a) * back);
  return { r: mix(color.r, backdrop.r), g: mix(color.g, backdrop.g), b: mix(color.b, backdrop.b), a: 1 };
}

const BLACK = { r: 0, g: 0, b: 0, a: 1 };
const WHITE = { r: 255, g: 255, b: 255, a: 1 };

// A translucent surface sits on a picture, so a text pair on it is checked against
// both a black and a white pixel and the lower ratio decides.
function overlayRatio(text, surface) {
  return Math.min(ratio(text, over(surface, BLACK)), ratio(text, over(surface, WHITE)));
}

// ---- token lookup ----

export function roleValue(tokens, name) {
  const key = name.replace(/^--/, '');
  const paletteKey = tokens.color.roles[key];
  if (paletteKey) return tokens.color.palette[paletteKey];
  const overlay = tokens.color.overlays[key];
  if (overlay) return overlay;
  throw new Error(`unknown color token: ${name}`);
}

export function pairRatio(tokens, text, surface) {
  const front = parseColor(roleValue(tokens, text));
  const back = parseColor(roleValue(tokens, surface));
  return back.a < 1 ? overlayRatio(front, back) : ratio(front, back);
}

// A colour written into a part instead of a role token: a hex value or a colour
// function. `color-mix(...)` and a URL fragment are not colours.
const HEX_COLOR = /(?<![\w&])#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![\w-])/;
const COLOR_FUNCTION = /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/;

export function directColorLiteral(text) {
  return HEX_COLOR.test(text) || COLOR_FUNCTION.test(text);
}

// ---- state resolution ----

function variantsOf(part) {
  return part.variants ? Object.keys(part.variants) : [null];
}

function restOf(part, variant) {
  return variant ? part.variants[variant] : part.rest;
}

// One row per state or per co-active state set. A cell comes from the highest
// precedence state that sets it, then from the resting style of the part.
function resolveRow(part, variant, states) {
  const rest = restOf(part, variant) ?? {};
  const winners = {};
  for (const state of part.precedence) {
    if (!states.includes(state)) continue;
    for (const [key, value] of Object.entries(part.overrides?.[state] ?? {})) {
      if (!(key in winners)) winners[key] = state;
    }
  }
  const pick = (key) => (winners[key] ? part.overrides[winners[key]][key] : rest[key] ?? null);
  return {
    part: part.part,
    variant,
    states,
    state: states.join(' + '),
    surface: pick('surface'),
    text: pick('text'),
    icon: pick('icon'),
    border: pick('border'),
    winners,
    kind: part.textKind ?? 'text',
    focus: part.focus,
    note: states.length === 1 ? part.notes?.[states[0]] ?? '' : '',
  };
}

export function resolveStates(tokens) {
  const rows = [];
  for (const part of tokens.states.parts) {
    for (const variant of variantsOf(part)) {
      for (const state of part.states) {
        const row = resolveRow(part, variant, [state]);
        row.changed = Object.keys(part.overrides?.[state] ?? {});
        rows.push(row);
      }
    }
  }
  return rows;
}

export function resolveCombos(tokens) {
  const rows = [];
  for (const part of tokens.states.parts) {
    for (const variant of variantsOf(part)) {
      for (const combo of part.combos) {
        const row = resolveRow(part, variant, combo);
        row.changed = [];
        rows.push(row);
      }
    }
  }
  return rows;
}

export function allRows(tokens) {
  return [...resolveStates(tokens), ...resolveCombos(tokens)];
}

export function focusLabel(tokens, focus) {
  if (focus === 'inset') return `안쪽 ${tokens.focus['offset-inset']}`;
  if (focus === 'card') return `바깥 ${tokens.focus['offset-card']}`;
  if (focus === 'outer') return `바깥 ${tokens.focus.offset}`;
  return '없음';
}

// The colours a focus ring is drawn against: its own fill when it sits inside,
// otherwise the surfaces of the parts around it.
export const RING_PARENTS = ['--background', '--card', '--popover'];

export function ringSurfaces(tokens, row) {
  return row.focus === 'inset' ? [row.surface] : RING_PARENTS;
}

export function reasonFor(tokens, part, state) {
  return part.skip?.[state] ?? tokens.states.reasons[state] ?? '';
}

// ---- stylesheet ----

function fontUrl(output, file) {
  const rel = relative(dirname(output), join(TOKEN_DIR, file)).split('\\').join('/');
  return rel.startsWith('.') ? rel : `./${rel}`;
}

function rule(name, value) {
  return `  --${name}: ${value};`;
}

/** The hand-kept shell block, copied into the generated stylesheet. */
export function shellCss() {
  return readFileSync(SHELL_PATH, 'utf8');
}

export function renderCss(tokens, output) {
  const lines = [];
  lines.push('/* Generated from tokens.json and shell.css by design/tokens/build.mjs. Do not edit by hand. */');
  lines.push('');
  for (const file of tokens.fonts.files) {
    lines.push('@font-face {');
    lines.push(`  font-family: "${file.family}";`);
    lines.push('  font-style: normal;');
    lines.push(`  font-weight: ${file.weight};`);
    lines.push('  font-display: swap;');
    lines.push(`  src: url("${fontUrl(output, file.file)}") format("woff2");`);
    lines.push('}');
    lines.push('');
  }
  lines.push(':root {');
  lines.push('  /* palette */');
  for (const [name, value] of Object.entries(tokens.color.palette)) {
    lines.push(rule(`palette-${name}`, value));
  }
  lines.push('  /* roles */');
  for (const [name, paletteKey] of Object.entries(tokens.color.roles)) {
    lines.push(rule(name, `var(--palette-${paletteKey})`));
  }
  lines.push('  /* surfaces over pictures */');
  for (const [name, value] of Object.entries(tokens.color.overlays)) {
    lines.push(rule(name, value));
  }
  lines.push('  /* typography */');
  lines.push(rule('font-family-sans', tokens.typography.family));
  for (const [name, value] of Object.entries(tokens.typography.sizes)) {
    lines.push(rule(`font-size-${name}`, value));
  }
  for (const [name, value] of Object.entries(tokens.typography.lineHeights)) {
    lines.push(rule(`line-height-${name}`, value));
  }
  for (const [name, value] of Object.entries(tokens.typography.weights)) {
    lines.push(rule(`font-weight-${name}`, value));
  }
  lines.push('  /* space */');
  for (const [name, value] of Object.entries(tokens.space)) {
    lines.push(rule(`space-${name}`, value));
  }
  lines.push('  /* size */');
  for (const [name, value] of Object.entries(tokens.size)) {
    lines.push(rule(`size-${name}`, value));
  }
  lines.push('  /* radius */');
  for (const [name, value] of Object.entries(tokens.radius)) {
    lines.push(rule(`radius-${name}`, value));
  }
  lines.push('  /* shadow */');
  for (const [name, value] of Object.entries(tokens.shadow)) {
    lines.push(rule(`shadow-${name}`, value));
  }
  lines.push('  /* layer */');
  for (const [name, value] of Object.entries(tokens.layer)) {
    lines.push(rule(`z-${name}`, value));
  }
  lines.push('  /* focus */');
  for (const [name, value] of Object.entries(tokens.focus)) {
    lines.push(rule(`focus-${name}`, value));
  }
  lines.push('  /* icon */');
  for (const [name, value] of Object.entries(tokens.icon)) {
    lines.push(rule(`icon-${name}`, value));
  }
  lines.push('  /* motion */');
  lines.push(rule('motion-ease', tokens.motion.ease));
  for (const [name, value] of Object.entries(tokens.motion.durations)) {
    lines.push(rule(`motion-${name}-duration`, value));
  }
  lines.push('}');
  lines.push('');
  lines.push('/* ---- shell ---- */');
  lines.push('');
  lines.push(shellCss().trim());
  lines.push('');
  lines.push('/* Dark mode is not decided. Override the same role names under a .dark selector when it is. */');
  lines.push('');
  lines.push('@media (prefers-reduced-motion: reduce) {');
  lines.push('  :root {');
  for (const name of Object.keys(tokens.motion.durations)) {
    lines.push(`    --motion-${name}-duration: 0ms;`);
  }
  lines.push('  }');
  lines.push('}');
  lines.push('');
  return lines.join('\n');
}

// ---- contrast report ----

function acceptedKey(text, surface) {
  return `${text} ${surface}`;
}

export function textVerdict(tokens, text, surface) {
  const accepted = new Set();
  for (const exception of tokens.contrast.exceptions) {
    if (exception.kind !== 'accepted') continue;
    for (const candidate of exception.surfaces) accepted.add(acceptedKey(exception.text, candidate));
  }
  const disabledText = tokens.contrast.exceptions
    .filter((exception) => exception.kind === 'disabled')
    .map((exception) => exception.text);
  const value = pairRatio(tokens, text, surface);
  let verdict = '통과';
  if (accepted.has(acceptedKey(text, surface))) verdict = '감수';
  else if (disabledText.includes(text)) verdict = 'WCAG 예외';
  else if (value < 4.5) verdict = '금지';
  return { value, verdict };
}

export function contrastReport(tokens) {
  const text = [];
  const forbidden = [];
  for (const front of tokens.contrast.textRoles) {
    for (const back of tokens.contrast.surfaces) {
      const { value, verdict } = textVerdict(tokens, front, back);
      const row = { text: front, surface: back, value, verdict };
      text.push(row);
      if (verdict === '금지') forbidden.push(row);
    }
  }

  const overlays = tokens.contrast.overlays.map((pair) => {
    const value = pairRatio(tokens, pair.text, pair.surface);
    return { ...pair, value, verdict: value >= 4.5 ? '통과' : '금지' };
  });

  const ring = new Map();
  for (const row of allRows(tokens)) {
    if (row.border !== '--ring') continue;
    for (const surface of ringSurfaces(tokens, row)) {
      const key = acceptedKey('--ring', surface);
      if (ring.has(key)) continue;
      ring.set(key, { text: '--ring', surface, value: pairRatio(tokens, '--ring', surface) });
    }
  }
  const ringRows = [...ring.values()].map((row) => ({ ...row, verdict: row.value >= 3 ? '통과' : '금지' }));

  const icons = [];
  for (const entry of tokens.contrast.icons) {
    for (const back of entry.surfaces) {
      const value = pairRatio(tokens, entry.color, back);
      icons.push({ text: entry.color, surface: back, value, verdict: value >= 3 ? '통과' : '금지' });
    }
  }

  const acceptedRows = text.filter((row) => row.verdict === '감수');
  const disabledRows = text.filter((row) => row.verdict === 'WCAG 예외');
  return {
    text,
    overlays,
    ring: ringRows,
    icons,
    accepted: acceptedRows,
    disabled: disabledRows,
    forbidden,
  };
}

export function contrastProblems(tokens) {
  const report = contrastReport(tokens);
  const problems = [];
  const disabledTexts = tokens.contrast.exceptions
    .filter((exception) => exception.kind === 'disabled')
    .map((exception) => exception.text);
  for (const row of allRows(tokens)) {
    if (row.text) {
      const { value, verdict } = textVerdict(tokens, row.text, row.surface);
      if (row.kind === 'icon') {
        if (verdict !== 'WCAG 예외' && value < 3) {
          problems.push(`icon ${row.part} ${row.state}: ${row.text} on ${row.surface} ${pair(value)}`);
        }
      } else if (verdict === '금지') {
        problems.push(`state ${row.part} ${row.state}: ${row.text} on ${row.surface} ${pair(value)}`);
      }
    }
    if (row.icon) {
      const declared = tokens.contrast.icons.some(
        (entry) => entry.color === row.icon && entry.surfaces.includes(row.surface),
      );
      if (!declared) {
        problems.push(`icon ${row.part} ${row.state}: ${row.icon} on ${row.surface} is not declared`);
      } else if (!disabledTexts.includes(row.icon)) {
        const iconValue = pairRatio(tokens, row.icon, row.surface);
        if (iconValue < 3) {
          problems.push(`icon ${row.part} ${row.state}: ${row.icon} on ${row.surface} ${pair(iconValue)}`);
        }
      }
    }
  }
  for (const row of [...report.overlays, ...report.ring, ...report.icons]) {
    if (row.verdict === '금지') problems.push(`non-text ${row.text} on ${row.surface} ${pair(row.value)}`);
  }
  return problems;
}

function pair(value) {
  return value.toFixed(2);
}

export function renderContrast(tokens) {
  const report = contrastReport(tokens);
  const lines = [];
  lines.push('# 대비');
  lines.push('');
  lines.push('`tokens.json`에서 만든 문서다. 값을 고치고 `node design/tokens/build.mjs`를 실행해 다시 만든다. 이 파일은 직접 고치지 않는다.');
  lines.push('');
  lines.push('## 글자와 바탕');
  lines.push('');
  lines.push('작은 글자는 4.5:1 이상이어야 한다. 이 제품의 글자 크기는 12px에서 22px까지이고 큰 문장 34px만 24px를 넘으므로 모든 조합을 4.5:1로 본다. 판정이 금지인 조합은 쓰지 않는다.');
  lines.push('');
  lines.push('| 글자 | 바탕 | 대비 | 판정 |');
  lines.push('| --- | --- | --- | --- |');
  for (const row of report.text) {
    lines.push(`| \`${row.text}\` | \`${row.surface}\` | ${pair(row.value)} | ${row.verdict} |`);
  }
  lines.push('');
  lines.push('## 그림 위의 반투명 면');
  lines.push('');
  lines.push('반투명 면은 그림 위에 놓이므로 검은 그림 픽셀과 흰 그림 픽셀 위에서 계산하고 낮은 값을 쓴다. 확인 창 뒤의 진한 회색 막(`--overlay-dialog-scrim`)은 글자를 얹지 않아 이 표에 넣지 않는다.');
  lines.push('');
  lines.push('| 글자 | 바탕 | 대비 | 판정 |');
  lines.push('| --- | --- | --- | --- |');
  for (const row of report.overlays) {
    lines.push(`| \`${row.text}\` | \`${row.surface}\` | ${pair(row.value)} | ${row.verdict} |`);
  }
  lines.push('');
  lines.push('## 의미 있는 아이콘과 포커스 표시 (3:1)');
  lines.push('');
  lines.push('### 포커스 표시');
  lines.push('');
  lines.push('포커스 표시는 그 표시가 그려지는 면과 견준다. 안쪽 선은 부품의 바탕과, 바깥 선은 부품을 둘러싼 부모 면과 견준다.');
  lines.push('');
  lines.push('| 표시 | 이웃한 면 | 대비 | 판정 |');
  lines.push('| --- | --- | --- | --- |');
  for (const row of report.ring) {
    lines.push(`| \`${row.text}\` | \`${row.surface}\` | ${pair(row.value)} | ${row.verdict} |`);
  }
  lines.push('');
  lines.push('### 아이콘');
  lines.push('');
  lines.push('부품의 상태 색표에 적힌 아이콘 색은 모두 이 표 안에 있어야 한다.');
  lines.push('');
  lines.push('| 아이콘 | 면 | 대비 | 판정 |');
  lines.push('| --- | --- | --- | --- |');
  for (const row of report.icons) {
    lines.push(`| \`${row.text}\` | \`${row.surface}\` | ${pair(row.value)} | ${row.verdict} |`);
  }
  lines.push('');
  lines.push('## 감수한 조합');
  lines.push('');
  lines.push('작은 파랑 글자는 진한 변형을 만들지 않고 밝은 면에 그대로 쓴다. 이 조합만 4.5:1 아래를 감수한다.');
  lines.push('');
  for (const row of report.accepted) {
    lines.push(`- \`${row.text}\` on \`${row.surface}\`: ${pair(row.value)}`);
  }
  lines.push('');
  lines.push('## WCAG 예외');
  lines.push('');
  lines.push('쓸 수 없는 부품의 글자는 WCAG 대비 기준에서 제외한다.');
  lines.push('');
  for (const row of report.disabled) {
    lines.push(`- \`${row.text}\` on \`${row.surface}\`: ${pair(row.value)}`);
  }
  lines.push('');
  lines.push('## 금지 목록');
  lines.push('');
  lines.push('여기 적힌 조합은 4.5:1 아래이고 글자에 쓰지 않는다.');
  lines.push('');
  lines.push(
    `회색 바탕의 뜻 색 글자는 \`--muted-foreground\` ${pair(pairRatio(tokens, '--muted-foreground', '--muted'))}, \`--destructive\` ${pair(pairRatio(tokens, '--destructive', '--muted'))}, \`--warning\` ${pair(pairRatio(tokens, '--warning', '--muted'))}가 4.5를 넘고 \`--emphasis\`는 ${pair(pairRatio(tokens, '--emphasis', '--muted'))}로 못 미친다. 그래서 \`--emphasis\` 글자는 밝은 면에서 쓰고, 나머지 뜻 색은 회색 바탕에도 쓴다.`,
  );
  lines.push('');
  const byText = new Map();
  for (const row of report.forbidden) {
    if (!byText.has(row.text)) byText.set(row.text, []);
    byText.get(row.text).push(`\`${row.surface}\` (${pair(row.value)})`);
  }
  for (const [text, surfaces] of byText) {
    lines.push(`- \`${text}\`: ${surfaces.join(', ')}`);
  }
  lines.push('');
  return lines.join('\n');
}

// ---- state tables ----

function stateList(states) {
  return states.map((state) => `\`${state}\``).join(', ');
}

function comboList(combos) {
  if (combos.length === 0) return '없음';
  return combos.map((combo) => combo.map((state) => `\`${state}\``).join(' + ')).join(', ');
}

export function renderStates(tokens) {
  const lines = [];
  lines.push('# 상태');
  lines.push('');
  lines.push('`tokens.json`에서 만든 문서다. 값을 고치고 `node design/tokens/build.mjs`를 실행해 다시 만든다. 이 파일은 직접 고치지 않는다.');
  lines.push('');
  lines.push('## 상태 행렬');
  lines.push('');
  lines.push('부품마다 받을 수 있는 상태, 함께 켜질 수 있는 상태, 같은 속성을 다툴 때 이기는 순서를 적는다. 상태가 없으면 받지 않는다는 뜻이고 이유는 아래 표에 있다.');
  lines.push('');
  lines.push('| 부품 | 상태 | 함께 켜짐 | 우선순위 | 포커스 |');
  lines.push('| --- | --- | --- | --- | --- |');
  for (const part of tokens.states.parts) {
    lines.push(
      `| \`${part.part}\` | ${stateList(part.states)} | ${comboList(part.combos)} | ${part.precedence.map((state) => `\`${state}\``).join(' > ')} | ${focusLabel(tokens, part.focus)} |`,
    );
  }
  lines.push('');
  lines.push('## 해당 없는 상태의 이유');
  lines.push('');
  lines.push('| 부품 | 상태 | 이유 |');
  lines.push('| --- | --- | --- |');
  for (const part of tokens.states.parts) {
    for (const state of tokens.states.order) {
      if (part.states.includes(state)) continue;
      lines.push(`| \`${part.part}\` | \`${state}\` | ${reasonFor(tokens, part, state)} |`);
    }
  }
  lines.push('');
  lines.push('## 상태 색표');
  lines.push('');
  lines.push('글자 칸은 글자 색, 아이콘 칸은 아이콘 색이다. 두 칸이 같으면 아이콘이 글자와 같은 색이다. 바뀐 칸이 없으면 그 부품의 쉬는 모양 그대로다.');
  lines.push('');
  lines.push('| 부품 | 변형 | 상태 | 바탕 | 글자 | 아이콘 | 테두리 | 바뀐 칸 | 메모 |');
  lines.push('| --- | --- | --- | --- | --- | --- | --- | --- | --- |');
  const changedName = { surface: '바탕', text: '글자', icon: '아이콘', border: '테두리' };
  for (const row of resolveStates(tokens)) {
    const changed =
      row.changed.length === 0 ? '없음' : row.changed.map((key) => changedName[key] ?? key).join(', ');
    lines.push(
      `| \`${row.part}\` | ${row.variant ? `\`${row.variant}\`` : '-'} | \`${row.state}\` | \`${row.surface}\` | ${row.text ? `\`${row.text}\`` : '-'} | ${row.icon ? `\`${row.icon}\`` : '-'} | \`${row.border}\` | ${changed} | ${row.note} |`,
    );
  }
  lines.push('');
  lines.push('## 조합 색표');
  lines.push('');
  lines.push('함께 켜지는 상태마다 한 줄을 둔다. 같은 칸을 두 상태가 다투면 우선순위가 높은 상태가 이기고, 이긴 상태를 마지막 칸에 적는다.');
  lines.push('');
  lines.push('| 부품 | 변형 | 조합 | 바탕 | 글자 | 아이콘 | 테두리 | 이긴 상태 |');
  lines.push('| --- | --- | --- | --- | --- | --- | --- | --- |');
  for (const row of resolveCombos(tokens)) {
    const winners =
      Object.entries(row.winners)
        .map(([key, state]) => `${changedName[key] ?? key} ${state}`)
        .join(', ') || '없음';
    lines.push(
      `| \`${row.part}\` | ${row.variant ? `\`${row.variant}\`` : '-'} | ${row.states.map((state) => `\`${state}\``).join(' + ')} | \`${row.surface}\` | \`${row.text}\` | ${row.icon ? `\`${row.icon}\`` : '-'} | \`${row.border}\` | ${winners} |`,
    );
  }
  lines.push('');
  return lines.join('\n');
}

// ---- fonts ----

export function fontHashes(tokens) {
  const entries = [...tokens.fonts.files, tokens.fonts.license];
  return entries.map((entry) => ({
    file: entry.file,
    sha256: createHash('sha256').update(readFileSync(join(TOKEN_DIR, entry.file))).digest('hex'),
    recorded: entry.sha256,
  }));
}

// ---- entry point ----

export function renderAll(tokens) {
  return new Map([
    [OUTPUTS.css, renderCss(tokens, OUTPUTS.css)],
    [OUTPUTS.contrast, renderContrast(tokens)],
    [OUTPUTS.states, renderStates(tokens)],
  ]);
}

function stale(tokens) {
  const problems = [];
  for (const [path, content] of renderAll(tokens)) {
    let current = '';
    try {
      current = readFileSync(path, 'utf8');
    } catch {
      current = '';
    }
    if (current !== content) problems.push(path);
  }
  return problems;
}

function main(argv) {
  const tokens = loadTokens();
  if (argv.includes('--check')) {
    const problems = stale(tokens);
    for (const path of problems) console.error(`out of date: ${path}`);
    return problems.length === 0 ? 0 : 1;
  }
  for (const [path, content] of renderAll(tokens)) {
    writeFileSync(path, content);
  }
  for (const entry of fontHashes(tokens)) {
    if (entry.sha256 !== entry.recorded) {
      console.error(`font hash mismatch: ${entry.file}`);
      return 1;
    }
  }
  const problems = contrastProblems(tokens);
  for (const problem of problems) console.error(`contrast: ${problem}`);
  return problems.length === 0 ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = main(process.argv.slice(2));
}
