/**
 * Builds the dev gallery as a static, read-only site under `dist/gallery`.
 * The normal `npm run build` keeps making only the app entry.
 */
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'vite';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

await build({
  root,
  configFile: join(root, 'vite.config.ts'),
  base: './',
  build: {
    outDir: join(root, 'dist', 'gallery'),
    emptyOutDir: true,
    rollupOptions: { input: join(root, 'src', 'gallery', 'index.html') },
  },
});
