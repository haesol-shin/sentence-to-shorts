import { defineConfig, devices, type Project } from '@playwright/test';

const isCI = Boolean(process.env.CI);
// The screenshot baselines compare pixels, so they run in one project on one
// browser, and the other projects leave their tests alone.
const isVisual = process.env.PLAYWRIGHT_VISUAL === '1';
const baseURL = 'http://127.0.0.1:4173';

const projects: Project[] = [
  {
    name: 'chromium-mobile',
    testIgnore: ['tests/visual/**'],
    use: {
      browserName: 'chromium',
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
    },
  },
  {
    name: 'chromium-desktop',
    testIgnore: ['tests/visual/**'],
    use: {
      browserName: 'chromium',
      viewport: { width: 1920, height: 1080 },
    },
  },
];

if (isCI) {
  projects.push(
    {
      name: 'webkit-mobile',
      testIgnore: ['tests/visual/**'],
      use: { ...devices['iPhone 13'], browserName: 'webkit' },
    },
    {
      name: 'webkit-desktop',
      testIgnore: ['tests/visual/**'],
      use: {
        browserName: 'webkit',
        viewport: { width: 1920, height: 1080 },
      },
    },
  );
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
  webServer: {
    command: 'npm run dev',
    url: baseURL,
    timeout: 300_000,
    reuseExistingServer: !isCI,
    env: { VITE_API_MODE: 'mock' },
  },
});
