import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, test } from 'vitest';

import { COPY_CASES, COMPOSER_COPY_KEYS } from '../../src/gallery/copy/case-map';
import { scanCopyUsages, usagesOf } from '../../src/gallery/copy/scan';

const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

describe('copy usage scan', () => {
  test('test_10a_copy_scan_finds_a_literal_key_with_its_line', () => {
    const source = "const a = 1;\nconst label = t('shell.apiKey.save');\n";
    const scan = scanCopyUsages([{ path: 'src/app/a.tsx', text: source }]);
    expect(usagesOf(scan, 'shell.apiKey.save')).toEqual([{ path: 'src/app/a.tsx', line: 2 }]);
  });

  test('test_10a_copy_scan_matches_a_template_prefix', () => {
    const source = "const label = t(`shell.stage.${stage}`);";
    const scan = scanCopyUsages([{ path: 'src/app/stage.tsx', text: source }]);
    expect(usagesOf(scan, 'shell.stage.edit')).toEqual([{ path: 'src/app/stage.tsx', line: 1 }]);
    expect(usagesOf(scan, 'shell.other')).toEqual([]);
  });

  test('test_10a_copy_scan_finds_an_indirect_key_declaration', () => {
    const source = "const ITEMS = [{ labelKey: 'shell.nav.newVideo' }];";
    const known = new Set(['shell.nav.newVideo']);
    const scan = scanCopyUsages([{ path: 'src/app/shell/sidebar.tsx', text: source }], known);
    expect(usagesOf(scan, 'shell.nav.newVideo')).toEqual([
      { path: 'src/app/shell/sidebar.tsx', line: 1 },
    ]);
  });

  test('test_10a_copy_scan_finds_the_sidebar_key_source', () => {
    const sidebar = read('src/app/shell/sidebar.tsx');
    const known = new Set(['shell.nav.newVideo']);
    const scan = scanCopyUsages([{ path: 'src/app/shell/sidebar.tsx', text: sidebar }], known);
    const usages = usagesOf(scan, 'shell.nav.newVideo');
    expect(usages.length).toBeGreaterThan(0);
    expect(usages[0].path).toBe('src/app/shell/sidebar.tsx');
    expect(usages[0].line).toBeGreaterThan(20);
  });
});

describe('copy case map', () => {
  test('test_10a_copy_case_map_points_at_the_attachment_case', () => {
    expect(COPY_CASES[COMPOSER_COPY_KEYS.error]).toEqual({
      partId: 'composer',
      slug: 'attachments',
    });
    expect(COPY_CASES[COMPOSER_COPY_KEYS.remove]).toEqual({
      partId: 'composer',
      slug: 'attachments',
    });
    expect(COPY_CASES[COMPOSER_COPY_KEYS.send]).toEqual({
      partId: 'composer',
      slug: 'default',
    });
  });
});
