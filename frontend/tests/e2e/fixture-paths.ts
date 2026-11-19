import { dirname, resolve } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const backendPort = Number(process.env.APP_PORT ?? 4174);
const appPort = Number(process.env.E2E_APP_PORT ?? backendPort + 1);

// Playwright clears `test-results` before a run, so the fixture state lives in
// the ignored `.local` folder and only this helper removes it.
export const FIXTURE_ROOT = resolve(HERE, '../../../.local/e2e-ui');
export const PAIRING_FILE = resolve(FIXTURE_ROOT, 'pairing-url.txt');
export const AUTH_FILE = resolve(FIXTURE_ROOT, 'storage-state.json');

export const MOCK_APP_URL = 'http://127.0.0.1:4173';
export const FIXTURE_APP_URL = `http://127.0.0.1:${appPort}`;
export const BACKEND_URL = `http://127.0.0.1:${backendPort}`;
