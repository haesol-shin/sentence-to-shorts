import { defineConfig, type Project } from '@playwright/test';

import {
  AUTH_FILE,
  BACKEND_URL,
  FIXTURE_APP_URL,
  FIXTURE_ROOT,
  MOCK_APP_URL,
  PAIRING_FILE,
} from './tests/e2e/fixture-paths';

const isCI = Boolean(process.env.CI);
// The screenshot baselines compare pixels, so they run in one project on one
// browser, and the other projects leave their tests alone.
const isVisual = process.env.PLAYWRIGHT_VISUAL === '1';
// The fixture run pairs once against the backend and opens only the specs that
// need a real server; the mock run keeps the rest.
const isFixture = process.env.E2E_API === 'fixture';
const baseURL = isFixture ? FIXTURE_APP_URL : MOCK_APP_URL;
const backendPort = new URL(BACKEND_URL).port;
const fixturePort = new URL(FIXTURE_APP_URL).port;

const FIXTURE_MATCH = 'tests/e2e/**/*.spec.ts';
const MOCK_MATCH = '**/*.spec.ts';
// The mock specs encode the phone and 1920 layouts, so the 1280 project runs
// the app smoke there; the fixture specs run at both widths in either mode.
const NARROW_MOCK_MATCH = 'e2e/**/*.spec.ts';

/** Desktop projects only: the MVP drops the 390px mobile projects. */
function desktop(
  name: string,
  browserName: 'chromium' | 'webkit',
  viewport: { width: number; height: number },
  mockMatch: string,
): Project {
  return {
    name,
    testMatch: isFixture ? FIXTURE_MATCH : mockMatch,
    testIgnore: isFixture ? ['tests/visual/**'] : ['tests/visual/**', 'tests/e2e/**'],
    ...(isFixture ? { dependencies: ['fixture-setup'] } : {}),
    use: {
      browserName,
      viewport,
      ...(isFixture ? { storageState: AUTH_FILE } : {}),
    },
  };
}

const projects: Project[] = [
  desktop('chromium-desktop', 'chromium', { width: 1920, height: 1080 }, MOCK_MATCH),
  desktop('chromium-desktop-1280', 'chromium', { width: 1280, height: 800 }, NARROW_MOCK_MATCH),
];

if (isCI) {
  projects.push(desktop('webkit-desktop', 'webkit', { width: 1920, height: 1080 }, MOCK_MATCH));
}

// The pairing code is one-time, so one setup project pairs and saves the
// session cookie for every desktop project to reuse.
if (isFixture) {
  projects.push({
    name: 'fixture-setup',
    testMatch: 'tests/e2e/pair.setup.ts',
    use: { browserName: 'chromium' },
  });
}

// Only `PLAYWRIGHT_VISUAL=1 npx playwright test tests/visual` runs this project,
// so the app suite never compares pixels.
if (isVisual) {
  projects.push({
    name: 'visual-chromium',
    testMatch: 'tests/visual/**/*.spec.ts',
    use: { browserName: 'chromium' },
  });
}

export default defineConfig({
  testDir: '.',
  // Only `*.spec.ts` files run here; the vitest suites keep their `.test.ts` names.
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  reporter: isCI ? 'github' : 'list',
  // One baseline per part, state and width, drawn only on the CI runner. The
  // 0.2% pixel allowance covers the text edge rendering of a changed runner
  // image; a colour or layout change moves far more pixels than that.
  snapshotPathTemplate: 'tests/visual/baselines/{arg}{ext}',
  expect: {
    toHaveScreenshot: {
      animations: 'disabled',
      caret: 'hide',
      maxDiffPixelRatio: 0.002,
      scale: 'css',
    },
  },
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects,
  webServer: isFixture
    ? [
        {
          command: 'poetry run python -m tests.e2e_ui.fixture_server',
          cwd: '../core',
          url: `${BACKEND_URL}/api/v1/health`,
          timeout: 180_000,
          reuseExistingServer: false,
          gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
          env: {
            APP_PORT: backendPort,
            E2E_UI_ROOT: FIXTURE_ROOT,
            E2E_UI_PAIRING_FILE: PAIRING_FILE,
            E2E_APP_URL: FIXTURE_APP_URL,
          },
        },
        {
          command: 'node tests/e2e/vite-fixture.mjs',
          url: FIXTURE_APP_URL,
          timeout: 300_000,
          reuseExistingServer: false,
          env: {
            E2E_BACKEND_URL: BACKEND_URL,
            E2E_APP_PORT: fixturePort,
          },
        },
      ]
    : {
        command: 'npm run dev',
        url: baseURL,
        timeout: 300_000,
        reuseExistingServer: !isCI,
        env: { VITE_API_MODE: 'mock' },
      },
});
