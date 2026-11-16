import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import {
  OUTPUTS,
  allRows,
  contrastProblems,
  contrastReport,
  directColorLiteral,
  focusLabel,
  fontHashes,
  loadTokens,
  pairRatio,
  renderAll,
  renderStates,
  resolveCombos,
  resolveStates,
  textVerdict,
} from '../build.mjs';

const tokens = loadTokens();
const stateOrder = tokens.states.order;

// The decided values. Every entry comes from the token decision table; a token
// that is not listed here, or a listed value that is missing, fails.
const DECIDED = {
  palette: [
    '#FFFFFF',
    '#F7F8F9',
    '#F2F4F6',
    '#ECEDEF',
    '#E5E8EB',
    '#DADDE1',
    '#D5D8DC',
    '#C9CDD2',
    '#9AA0A8',
    '#6B7280',
    '#646B76',
    '#3A3F46',
    '#22262B',
    '#34383C',
    '#A9CBFA',
    '#3182F6',
    '#B45309',
    '#DC2626',
  ],
  overlays: [
    'rgba(255, 255, 255, 0.88)',
    'rgba(255, 255, 255, 0.92)',
    'rgba(0, 0, 0, 0.55)',
    'rgba(255, 255, 255, 0.55)',
    'rgba(34, 38, 43, 0.24)',
  ],
  roles: [
    'accent',
    'accent-foreground',
    'accent-pressed',
    'background',
    'border',
    'card',
    'card-foreground',
    'destructive',
    'disabled-foreground',
    'emphasis',
    'foreground',
    'input',
    'muted',
    'muted-foreground',
    'popover',
    'popover-foreground',
    'primary',
    'primary-foreground',
    'primary-hover',
    'primary-pressed',
    'ring',
    'secondary',
    'secondary-foreground',
    'state-hover-gray',
    'state-hover-white',
    'state-pressed-gray',
    'state-pressed-white',
    'state-selected',
    'sub',
    'warning',
  ],
  text: ['13px', '15px', '17px', '22px', '34px', '12px'],
  lineHeight: ['46px', '30px', '26px', '22px'],
  weight: ['400', '700'],
  space: ['4px', '8px', '12px', '16px', '20px', '24px', '36px', '48px'],
  control: ['44px'],
  radius: ['36px', '24px', '20px', '18px', '16px', '12px', '8px', '999px', '0px'],
  shadow: ['none', '0 12px 32px rgba(0, 0, 0, 0.16)', '-12px 0 32px rgba(0, 0, 0, 0.1)'],
  layer: ['20', '30', '40', '45', '50', '60', '70', '90', '95'],
  focusWidth: ['2px'],
  focusOffset: ['2px', '-2px', '6px'],
  icon: ['14px', '16px', '20px', '22px', '32px'],
  iconStroke: ['2px'],
  motion: ['120ms', '200ms', '0ms', '240ms'],
  easing: ['ease'],
};

const groups = [
  ...Object.keys(tokens.color.palette),
  ...Object.keys(tokens.color.roles),
  ...Object.keys(tokens.color.overlays),
];

const sorted = (values) => [...values].map(String).sort();

function unique(values) {
  return [...new Set(values)];
}

describe('design tokens', () => {
  test('test_1_only_decided_values', () => {
    expect(Object.keys(tokens).sort()).toEqual([
      'color',
      'contrast',
      'focus',
      'fonts',
      'icon',
      'layer',
      'motion',
      'radius',
      'shadow',
      'size',
      'space',
      'states',
      'typography',
    ]);
    expect(sorted(unique(Object.values(tokens.color.palette)))).toEqual(sorted(DECIDED.palette));
    expect(sorted(unique(Object.values(tokens.color.overlays)))).toEqual(sorted(DECIDED.overlays));
    expect(sorted(Object.keys(tokens.color.roles))).toEqual(sorted(DECIDED.roles));
    for (const [role, paletteKey] of Object.entries(tokens.color.roles)) {
      expect(tokens.color.palette, `role ${role}`).toHaveProperty(paletteKey);
    }
    expect(sorted(unique(Object.values(tokens.typography.sizes)))).toEqual(sorted(DECIDED.text));
    expect(sorted(unique(Object.values(tokens.typography.lineHeights)))).toEqual(sorted(DECIDED.lineHeight));
    expect(sorted(unique(Object.values(tokens.typography.weights)))).toEqual(sorted(DECIDED.weight));
    expect(tokens.typography.family).toContain('Pretendard');
    expect(sorted(unique(Object.values(tokens.space)))).toEqual(sorted(DECIDED.space));
    for (const [name, value] of Object.entries(tokens.space)) expect(value).toBe(`${name}px`);
    expect(sorted(unique(Object.values(tokens.size)))).toEqual(sorted(DECIDED.control));
    expect(sorted(unique(Object.values(tokens.radius)))).toEqual(sorted(DECIDED.radius));
    expect(sorted(unique(Object.values(tokens.shadow)))).toEqual(sorted(DECIDED.shadow));
    expect(sorted(unique(Object.values(tokens.layer)))).toEqual(sorted(DECIDED.layer));
    expect([tokens.focus.width]).toEqual(DECIDED.focusWidth);
    expect(
      sorted([tokens.focus.offset, tokens.focus['offset-inset'], tokens.focus['offset-card']]),
    ).toEqual(sorted(DECIDED.focusOffset));
    expect(
      sorted([
        tokens.icon.close,
        tokens.icon.inline,
        tokens.icon.default,
        tokens.icon.title,
        tokens.icon.placeholder,
      ]),
    ).toEqual(sorted(DECIDED.icon));
    expect([tokens.icon.stroke]).toEqual(DECIDED.iconStroke);
    expect(sorted(unique(Object.values(tokens.motion.durations)))).toEqual(sorted(DECIDED.motion));
    expect([tokens.motion.ease]).toEqual(DECIDED.easing);
    expect(groups).toHaveLength(new Set(groups).size);
  });

  test('test_1_colors_use_one_format', () => {
    for (const value of Object.values(tokens.color.palette)) {
      expect(value).toMatch(/^#[0-9A-F]{6}$/);
    }
    for (const value of Object.values(tokens.color.overlays)) {
      expect(value).toMatch(/^rgba\(\d{1,3}, \d{1,3}, \d{1,3}, 0?\.[0-9]+\)$/);
    }
    for (const value of Object.values(tokens.shadow)) {
      if (value === 'none') continue;
      expect(value).toMatch(/^(?:-?\d+(?:px)? ){1,3}rgba\(\d{1,3}, \d{1,3}, \d{1,3}, 0?\.[0-9]+\)$/);
    }
  });

  test('test_2_generated_files_match_the_source', () => {
    for (const [path, content] of renderAll(tokens)) {
      expect(readFileSync(path, 'utf8'), path).toBe(content);
    }
    const properties = (path) =>
      readFileSync(path, 'utf8')
        .split('\n')
        .filter((line) => line.startsWith('  --') && line.endsWith(';'));
    expect(properties(OUTPUTS.local)).toEqual(properties(OUTPUTS.css));
    expect(readFileSync(OUTPUTS.local, 'utf8')).toContain('../../../design/tokens/fonts/');
    expect(readFileSync(OUTPUTS.css, 'utf8')).toContain('url("./fonts/');
  });

  test('test_3_small_text_meets_4_5', () => {
    const rows = allRows(tokens);
    for (const row of rows) {
      if (row.text === null) continue;
      expect(tokens.contrast.textRoles, `${row.part} ${row.state}`).toContain(row.text);
      const knownSurface =
        tokens.contrast.surfaces.includes(row.surface) ||
        Object.keys(tokens.color.overlays).includes(row.surface.replace(/^--/, ''));
      expect(knownSurface, `${row.part} ${row.state} surface ${row.surface}`).toBe(true);
      if (row.icon) {
        const declared = tokens.contrast.icons.some(
          (entry) => entry.color === row.icon && entry.surfaces.includes(row.surface),
        );
        expect(declared, `${row.part} ${row.state} icon ${row.icon}`).toBe(true);
        expect(pairRatio(tokens, row.icon, row.surface), `${row.part} ${row.state} icon`).toBeGreaterThanOrEqual(3);
      }
      if (row.kind === 'icon') continue;
      const { value, verdict } = textVerdict(tokens, row.text, row.surface);
      expect(verdict, `${row.part} ${row.state}: ${value.toFixed(2)}`).not.toBe('금지');
    }
    const report = contrastReport(tokens);
    expect(report.text).toHaveLength(
      tokens.contrast.textRoles.length * tokens.contrast.surfaces.length,
    );
    const acceptedText = new Set(
      tokens.contrast.exceptions.filter((entry) => entry.kind === 'accepted').map((entry) => entry.text),
    );
    for (const row of report.text) {
      if (row.verdict === '통과') expect(row.value >= 4.5, `${row.text} on ${row.surface}`).toBe(true);
      if (row.verdict === '금지') expect(row.value < 4.5, `${row.text} on ${row.surface}`).toBe(true);
      if (row.verdict === '감수') {
        expect(acceptedText.has(row.text)).toBe(true);
        expect(row.value < 4.5).toBe(true);
      }
      if (row.verdict === 'WCAG 예외') expect(row.text).toBe('--disabled-foreground');
    }
    // The accepted pair is used, and the disabled exception is listed.
    const accepted = report.accepted.map((row) => `${row.text} ${row.surface}`);
    expect(accepted).toContain('--emphasis --card');
    expect(report.disabled.length).toBeGreaterThan(0);
    for (const row of report.disabled) expect(row.text).toBe('--disabled-foreground');
    expect(report.forbidden.length).toBeGreaterThan(0);
    for (const row of report.forbidden) expect(row.value < 4.5).toBe(true);
  });

  test('test_3_role_partition_is_complete', () => {
    const listed = [...tokens.contrast.textRoles, ...tokens.contrast.surfaces, ...tokens.contrast.neither];
    expect(sorted(listed)).toEqual(sorted(Object.keys(tokens.color.roles).map((name) => `--${name}`)));
    expect(listed).toHaveLength(new Set(listed).size);
  });

  test('test_4_focus_and_icons_meet_3', () => {
    const report = contrastReport(tokens);
    expect(report.ring.length).toBeGreaterThan(0);
    for (const row of report.ring) {
      expect(row.value >= 3, `ring on ${row.surface}: ${row.value.toFixed(2)}`).toBe(true);
      expect(row.verdict).toBe('통과');
    }
    expect(report.icons.length).toBeGreaterThan(0);
    for (const row of report.icons) {
      expect(row.value >= 3, `${row.text} on ${row.surface}: ${row.value.toFixed(2)}`).toBe(true);
      expect(row.verdict).toBe('통과');
    }
    const states = allRows(tokens);
    const insetRingRows = states.filter((row) => row.border === '--ring' && row.focus === 'inset');
    expect(insetRingRows.length).toBeGreaterThan(0);
    for (const row of states.filter((candidate) => candidate.border === '--ring')) {
      const surfaces = row.focus === 'inset' ? [row.surface] : ['--background', '--card', '--popover'];
      for (const surface of surfaces) {
        expect(report.ring.map((entry) => entry.surface)).toContain(surface);
      }
    }
  });

  test('test_5_font_files_match_the_record', () => {
    const hashes = fontHashes(tokens);
    expect(hashes.map((entry) => entry.file)).toEqual([
      'fonts/Pretendard-Regular.woff2',
      'fonts/Pretendard-Bold.woff2',
      'fonts/LICENSE.txt',
    ]);
    for (const entry of hashes) {
      expect(entry.sha256, entry.file).toBe(entry.recorded);
      expect(entry.sha256).toMatch(/^[0-9a-f]{64}$/);
    }
    expect(tokens.fonts.license.name).toBe('SIL Open Font License 1.1');
    expect(tokens.fonts.files.map((file) => file.weight)).toEqual([400, 700]);
    expect(tokens.fonts.files.map((file) => file.family)).toEqual(['Pretendard', 'Pretendard']);
  });

  test('test_6_state_colors_name_roles', () => {
    const roleNames = new Set(Object.keys(tokens.color.roles).map((name) => `--${name}`));
    const overlayNames = new Set(Object.keys(tokens.color.overlays).map((name) => `--${name}`));
    const rows = allRows(tokens);
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      for (const cell of [row.surface, row.text, row.border, row.icon]) {
        if (cell === null) continue;
        expect(roleNames.has(cell) || overlayNames.has(cell), `${row.part} ${row.state}: ${cell}`).toBe(true);
      }
    }
    const keys = rows.map((row) => `${row.part}|${row.variant ?? ''}|${row.state}`);
    expect(keys).toHaveLength(new Set(keys).size);
  });

  test('test_7_state_matrix_covers_every_state', () => {
    const parts = tokens.states.parts;
    expect(parts.length).toBeGreaterThan(0);
    expect(tokens.states.order).toHaveLength(10);
    const rows = resolveStates(tokens);
    for (const part of parts) {
      const skip = part.skip ?? {};
      for (const state of stateOrder) {
        const applicable = part.states.includes(state);
        expect(applicable || state in skip, `${part.part} ${state}`).toBe(true);
        expect(applicable && state in skip, `${part.part} ${state} both`).toBe(false);
        if (!applicable) expect(skip[state].length, `${part.part} ${state} reason`).toBeGreaterThan(0);
      }
      for (const state of part.states) {
        const matching = rows.filter((row) => row.part === part.part && row.state === state);
        expect(matching.length, `${part.part} ${state} rows`).toBe(
          part.variants ? Object.keys(part.variants).length : 1,
        );
      }
      expect(sorted(part.precedence)).toEqual(sorted(part.states));
      const variantNames = part.variants ? Object.keys(part.variants) : [null];
      const comboRows = resolveCombos(tokens).filter((row) => row.part === part.part);
      expect(comboRows.length, `${part.part} combo rows`).toBe(part.combos.length * variantNames.length);
      for (const combo of part.combos) {
        expect(combo.length).toBeGreaterThan(1);
        for (const state of combo) expect(part.states).toContain(state);
        if (part.focus === 'inset') {
          expect(combo.includes('pressed') && combo.includes('focus-visible')).toBe(false);
        }
      }
      for (const row of comboRows) {
        for (const [key, state] of Object.entries(row.winners)) {
          const index = part.precedence.indexOf(state);
          const higher = row.states.filter(
            (candidate) =>
              part.precedence.indexOf(candidate) < index &&
              part.overrides?.[candidate]?.[key] !== undefined,
          );
          expect(higher, `${part.part} ${row.state} ${key}`).toEqual([]);
        }
      }
    }
    const rowKeys = new Set(rows.map((row) => `${row.part}|${row.variant ?? ''}|${row.state}`));
    for (const part of parts) {
      for (const state of part.states) {
        for (const variant of part.variants ? Object.keys(part.variants) : ['']) {
          expect(rowKeys.has(`${part.part}|${variant}|${state}`), `${part.part} ${state}`).toBe(true);
        }
      }
    }
  });

  test('test_8_motion_has_three_kinds', () => {
    for (const kind of ['state', 'panel', 'screen']) {
      expect(tokens.motion.durations).toHaveProperty(kind);
      expect(tokens.motion.kinds).toHaveProperty(kind);
      expect(tokens.motion.kinds[kind].length).toBeGreaterThan(0);
    }
    expect(tokens.motion.durations.screen).toBe('0ms');
    expect(tokens.motion.durations.panel).toBe('200ms');
    const css = readFileSync(OUTPUTS.css, 'utf8');
    const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
    for (const name of Object.keys(tokens.motion.durations)) {
      expect(reduced).toContain(`--motion-${name}-duration: 0ms;`);
    }
    expect(css).toContain('.dark');
  });

  test('test_9_contrast_pairs_are_computed_from_tokens', () => {
    // Changing a palette value moves every ratio that uses it.
    const probe = structuredClone(tokens);
    probe.color.palette['gray-9'] = '#000000';
    const before = pairRatio(tokens, '--muted-foreground', '--card');
    const after = pairRatio(probe, '--muted-foreground', '--card');
    expect(after).toBeGreaterThan(before);
    expect(pairRatio(probe, '--foreground', '--card')).toBe(
      pairRatio(tokens, '--foreground', '--card'),
    );
    expect(renderAll(probe).get(OUTPUTS.contrast)).not.toBe(renderAll(tokens).get(OUTPUTS.contrast));
  });

  test('test_10_components_name_roles_only', () => {
    // The parts and their gallery read role tokens from the generated stylesheet. A
    // palette reference or a colour written into the file is a second source of
    // colour. The rest of frontend/src (app/, features/, shared/) still uses the shell
    // styles until the screen migration moves it onto these parts, so it joins then.
    const root = fileURLToPath(new URL('../../../frontend/src/', import.meta.url));
    const tokenFile = join(root, 'components', 'tokens.local.css');
    const files = [];
    const walk = (dir) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name === 'node_modules' || entry.name === 'generated') continue;
          walk(path);
        } else if (/\.(?:ts|tsx|css)$/.test(entry.name)) {
          files.push(path);
        }
      }
    };
    for (const dir of ['components', 'gallery']) {
      const before = files.length;
      walk(join(root, dir));
      expect(files.length, `${dir}/ has files to check`).toBeGreaterThan(before);
    }
    for (const path of files) {
      const text = readFileSync(path, 'utf8');
      if (path === tokenFile) continue;
      expect(text, `${relative(root, path)} names a palette token`).not.toContain('--palette-');
      expect(directColorLiteral(text), `${relative(root, path)} writes a colour`).toBe(false);
    }
    // The detector must catch both paths the parts can write a colour through.
    expect(directColorLiteral('<div className="bg-[#3182F6]" />')).toBe(true);
    expect(directColorLiteral('style={{ color: "#22262B" }}')).toBe(true);
    expect(directColorLiteral('border: 1px solid rgba(0, 0, 0, 0.2);')).toBe(true);
    expect(directColorLiteral('box-shadow: 0 0 0 2px hsla(0, 0%, 0%, 0.1);')).toBe(true);
    expect(directColorLiteral('background: var(--card);')).toBe(false);
    expect(directColorLiteral('color-mix(in srgb, var(--muted), var(--card))')).toBe(false);
    expect(directColorLiteral('<a href="#fallback">')).toBe(false);
  });

  test('test_11_focus_labels_follow_the_source', () => {
    const probe = structuredClone(tokens);
    probe.focus.offset = '9px';
    probe.focus['offset-inset'] = '-9px';
    probe.focus['offset-card'] = '13px';
    expect(focusLabel(probe, 'outer')).toBe('바깥 9px');
    expect(focusLabel(probe, 'inset')).toBe('안쪽 -9px');
    expect(focusLabel(probe, 'card')).toBe('바깥 13px');
    expect(focusLabel(probe, 'none')).toBe('없음');
    const rendered = renderStates(probe);
    for (const label of ['바깥 9px', '안쪽 -9px', '바깥 13px']) expect(rendered).toContain(label);
    expect(renderStates(tokens)).not.toBe(rendered);
  });

  test('test_12_contrast_gate_covers_the_tables', () => {
    expect(contrastProblems(tokens)).toEqual([]);
    // A row that uses an under-threshold pair is reported instead of passing.
    const probe = structuredClone(tokens);
    probe.contrast.exceptions = probe.contrast.exceptions.filter((entry) => entry.kind !== 'accepted');
    expect(contrastProblems(probe).length).toBeGreaterThan(0);
    const iconProbe = structuredClone(tokens);
    iconProbe.contrast.icons = iconProbe.contrast.icons.filter((entry) => entry.color !== '--emphasis');
    expect(contrastProblems(iconProbe).some((problem) => problem.includes('is not declared'))).toBe(true);
  });

  test('test_13_combos_use_the_same_checked_pairs', () => {
    const combos = resolveCombos(tokens);
    expect(combos.length).toBe(47);
    for (const row of combos) {
      expect(tokens.contrast.textRoles).toContain(row.text);
      const knownSurface =
        tokens.contrast.surfaces.includes(row.surface) ||
        Object.keys(tokens.color.overlays).includes(row.surface.replace(/^--/, ''));
      expect(knownSurface, `${row.part} ${row.state}`).toBe(true);
      if (row.kind === 'icon') continue;
      expect(textVerdict(tokens, row.text, row.surface).verdict).not.toBe('금지');
    }
    // A combo takes the cell of the state that wins the precedence order.
    const tab = resolveCombos(tokens).find(
      (row) => row.part === 'tab.item' && row.states.join('+') === 'selected+focus-visible',
    );
    expect(tab.text).toBe('--foreground');
    expect(tab.border).toBe('--ring');
    expect(tab.winners).toMatchObject({ text: 'selected', border: 'focus-visible' });
    const trigger = resolveCombos(tokens).find(
      (row) => row.part === 'button.trigger' && row.states.join('+') === 'open+pressed',
    );
    expect(trigger.surface).toBe('--state-pressed-gray');
    expect(trigger.winners).toMatchObject({ surface: 'pressed' });
  });
});
