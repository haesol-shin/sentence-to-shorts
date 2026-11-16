import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, test } from 'vitest';

const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

describe('gallery configuration', () => {
  test('test_10a_dev_server_binds_to_the_tailscale_host_or_localhost_only', () => {
    const config = read('vite.config.ts');
    expect(config).toContain('APP_GALLERY_HOST');
    expect(config).toContain('APP_PORT');
    expect(config).toContain("'127.0.0.1'");
    expect(config).not.toContain('0.0.0.0');
  });

  test('test_10a_app_entry_does_not_import_the_gallery', () => {
    expect(read('src/app/App.tsx')).not.toContain('gallery');
    expect(read('src/app/main.tsx')).not.toContain('gallery');
    expect(read('index.html')).not.toContain('gallery');
  });

  test('test_10a_no_storybook_dependency', () => {
    const packageJson = JSON.parse(read('package.json')) as {
      dependencies: Record<string, string>;
      devDependencies: Record<string, string>;
    };
    const names = [
      ...Object.keys(packageJson.dependencies),
      ...Object.keys(packageJson.devDependencies),
    ];
    expect(names.some((name) => name.includes('storybook'))).toBe(false);
    expect(read('src/gallery/gallery.tsx')).not.toContain('storybook');
  });
});
