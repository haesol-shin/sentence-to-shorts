import { fileURLToPath, URL } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

import { copyIndexPlugin } from './vite-plugins/copy-index';
import { copySavePlugin } from './vite-plugins/copy-save';

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    copyIndexPlugin({ edit: process.env.APP_COPY_EDIT === '1' }),
    copySavePlugin({ edit: process.env.APP_COPY_EDIT === '1' }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // The dev gallery binds to the Tailscale address when the host gives one.
    // This server is not for the public internet.
    host: process.env.APP_GALLERY_HOST ?? '127.0.0.1',
    port: Number(process.env.APP_PORT ?? 4173),
    strictPort: true,
    fs: {
      // A mock run serves the recorded answers from `fixtures/api/` one level up.
      allow: ['..'],
    },
  },
  test: {
    environment: 'jsdom',
    // Part tests live next to their part so the acceptance command can name the folder.
    include: ['tests/**/*.test.{ts,tsx}', 'src/components/**/*.test.{ts,tsx}'],
  },
});
