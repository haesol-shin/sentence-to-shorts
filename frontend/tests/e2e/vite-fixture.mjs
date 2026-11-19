/* global process, URL */
import { fileURLToPath } from 'node:url';

import { createServer } from 'vite';

const backend = new URL(process.env.E2E_BACKEND_URL);
const backendOrigin = backend.origin;
const configFile = fileURLToPath(new URL('../../vite.config.ts', import.meta.url));

// The browser opens the app origin, so the API has to answer there. The
// backend checks Host and Origin against its own port, and the proxy rewrites
// both; the session cookie still belongs to the app origin.
const server = await createServer({
  configFile,
  server: {
    host: '127.0.0.1',
    port: Number(process.env.E2E_APP_PORT),
    strictPort: true,
    proxy: {
      '/api': {
        target: backendOrigin,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (request) => {
            request.setHeader('origin', backendOrigin);
          });
        },
      },
    },
  },
});

await server.listen();
server.printUrls();
