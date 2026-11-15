import { expect } from '@playwright/test';

import { test } from './mock';

test('test_4_screen_fits_the_viewport', async ({ page }) => {
  await page.goto('/');

  await expect(page.locator('main[data-screen="app"]')).toBeVisible();

  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflows).toBe(false);
});
