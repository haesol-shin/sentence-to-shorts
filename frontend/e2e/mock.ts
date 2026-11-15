import { test as base } from '@playwright/test';

import type { RuntimeStatus } from '../src/shared/api/client';

const runtime: RuntimeStatus = {
  app_version: '0.0.0',
  profile: 'fixture',
  deployment: 'local',
  brand: {
    display_name_ko: '예시 스튜디오',
    display_name_en: 'Example Studio',
  },
  items: [],
  llm_auth: { adapter: 'fixture', state: 'unknown' },
  capabilities: {
    open_edit_play: true,
    render: true,
    tts: true,
    llm: true,
    link_download: true,
  },
};

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.route('**/api/v1/runtime', (route) =>
      route.fulfill({ json: runtime }),
    );
    await use(page);
  },
});
