import { readFileSync } from 'node:fs';

import { expect, test as setup } from '@playwright/test';

import { AUTH_FILE, PAIRING_FILE } from './fixture-paths';

async function pairingUrl(): Promise<string> {
  let found = '';
  await expect
    .poll(
      () => {
        try {
          found = readFileSync(PAIRING_FILE, 'utf-8').trim();
        } catch {
          found = '';
        }
        return found;
      },
      { timeout: 15_000 },
    )
    .not.toBe('');
  return found;
}

/**
 * The fixture server issues one pairing code per start. Pair once here and
 * save the session cookie, because every desktop project gets its own browser
 * context and a spent code cannot pair again.
 */
setup('pair with the fixture backend', async ({ page }) => {
  await page.goto(await pairingUrl());

  await expect(page.getByRole('heading', { name: '어떤 영상을 만들까요?' })).toBeVisible();
  // The catalog is behind the session, so three cards prove the pairing took.
  await expect(page.locator('[data-slot="first-cards"] button')).toHaveCount(3);

  await page.context().storageState({ path: AUTH_FILE });
});
