import { execFileSync } from 'node:child_process';
import { mkdirSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, test } from 'vitest';

const ROOT = process.cwd();
const OUT_ROOT = join(ROOT, 'test-results');

function filesUnder(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...filesUnder(path));
    else found.push(path);
  }
  return found;
}

function build(mode: 'fixture' | 'release'): string {
  const out = join(OUT_ROOT, `gallery-bundle-${mode}`);
  rmSync(out, { recursive: true, force: true });
  mkdirSync(OUT_ROOT, { recursive: true });
  execFileSync(join(ROOT, 'node_modules', '.bin', 'vite'), ['build', '--outDir', out, '--emptyOutDir'], {
    cwd: ROOT,
    env: { ...process.env, VITE_API_MODE: mode },
    stdio: 'pipe',
  });
  return out;
}

describe('gallery build profile', () => {
  test(
    'test_10a_fixture_and_release_bundles_have_no_gallery_route',
    () => {
      for (const mode of ['fixture', 'release'] as const) {
        const out = build(mode);
        const text = filesUnder(out)
          .map((file) => readFileSync(file, 'utf8'))
          .join('\n');
        expect(text).not.toContain('부품 갤러리');
        expect(text).not.toContain('case-frame');
        expect(text).not.toContain('data-frame-part');
      }
    },
    180_000,
  );
});
