import { defineConfig, devices, type Project } from '@playwright/test';

const isCI = Boolean(process.env.CI);
const baseURL = 'http://127.0.0.1:4173';

const projects: Project[] = [
  {
    name: 'chromium-mobile',
    use: {
      browserName: 'chromium',
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
    },
  },
  {
    name: 'chromium-desktop',
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
      use: { ...devices['iPhone 13'], browserName: 'webkit' },
    },
    {
      name: 'webkit-desktop',
      use: {
        browserName: 'webkit',
        viewport: { width: 1920, height: 1080 },
      },
    },
  );
}

export default defineConfig({
  testDir: '.',
  // Only `*.spec.ts` files run here; the vitest suites keep their `.test.ts` names.
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  reporter: isCI ? 'github' : 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects,
  webServer: {
    command: 'npm run dev',
    url: baseURL,
    reuseExistingServer: !isCI,
    env: { VITE_API_MODE: 'mock' },
  },
});
