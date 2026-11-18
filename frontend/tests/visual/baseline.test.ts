import { spawnSync } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, test } from 'vitest';

/**
 * The design baseline: one generated stylesheet for parts and screens, a guide
 * a newcomer can read in two pages, and rules an agent cannot miss.
 */
const ROOT = join(process.cwd(), '..');

/** The sections the design guide must keep, in this order. */
const SECTIONS = [
  '브랜드',
  'Overview',
  'Colors',
  'Typography',
  'Layout',
  'Elevation & Depth',
  'Shapes',
  'Motion',
  'Components',
  'Voice & Microcopy',
  "Do's and Don'ts",
  '검증',
];

function read(path: string): string {
  return readFileSync(join(ROOT, path), 'utf8');
}

describe('design baseline', () => {
  test('test_23_tokens_stylesheet_is_generated_from_the_approved_source', () => {
    const check = spawnSync(process.execPath, ['design/tokens/build.mjs', '--check'], {
      cwd: ROOT,
      encoding: 'utf8',
    });
    expect(check.stderr, check.stderr).not.toContain('out of date');
    expect(check.status).toBe(0);

    const tokens = JSON.parse(read('design/tokens/tokens.json')) as {
      color: { palette: Record<string, string>; roles: Record<string, string> };
    };
    expect(tokens.color.palette[tokens.color.roles.progress]).toBe('#1B64DA');

    const css = read('frontend/src/shared/ui/tokens.css');
    expect(css).toContain('--progress: var(--palette-blue-deep);');
    expect(css).toContain('--font-family-sans: "Pretendard", system-ui, sans-serif;');
    expect(css).toContain('--layout-sidebar-w: 72px;');

    // One stylesheet for parts and screens: no second token file anywhere.
    expect(readdirSync(join(ROOT, 'frontend', 'src', 'components'))).not.toContain('tokens.local.css');
    expect(read('frontend/src/components/base.css').split('\n')[0]).toBe(
      "@import '../shared/ui/tokens.css';",
    );
    expect(read('frontend/src/app/index.css')).toContain('font-family: var(--font-family-sans);');
  });

  test('test_23_design_guide_stays_within_two_pages', () => {
    const guide = read('DESIGN.md');
    // A printed page holds about 55 lines at the body size; two pages are 110.
    expect(guide.split('\n').filter((line) => line.trim() !== '').length).toBeLessThanOrEqual(110);
    const headings = [...guide.matchAll(/^## (.+)$/gm)].map((match) => match[1]);
    expect(headings).toEqual(SECTIONS);
  });

  test('test_23_approved_part_rules_are_in_the_agent_guide', () => {
    const agents = read('AGENTS.md');
    expect(agents).toContain('## 디자인');
    expect(agents).toContain('`frontend/src/components/`의 승인된 부품');
    expect(agents).toContain('token에 없는 값을 직접 쓰지 않는다');
    expect(agents).toContain('`frontend/tests/visual`의 baseline');
    expect(agents).toContain('`design/tokens/tokens.json`과 `design/tokens/shell.css`에서 만든 파일');
  });

  test('test_23_design_text_has_no_owner_quote_or_internal_path', () => {
    const forbidden: [RegExp, string][] = [
      [/\u300c|\u300d/, 'quoted owner words'],
      [/\b20\d\d[-./]\d{1,2}/, 'a decision date'],
      [/\/home\/|Homebase|00_Inbox|seafile/, 'an internal path'],
      [/텔레그램|Telegram/, 'an owner quote source'],
    ];
    for (const path of ['DESIGN.md', 'AGENTS.md']) {
      const text = read(path);
      for (const [pattern, label] of forbidden) {
        expect(pattern.test(text), `${path} has ${label}`).toBe(false);
      }
    }
  });
});
