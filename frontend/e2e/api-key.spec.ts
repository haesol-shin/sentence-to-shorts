import { expect, test } from '@playwright/test';

import { capture } from '../tests/support/capture';

// Writes the capture under `.local/`, which git ignores; a run on a laptop
// keeps the 1280 and 1920 images beside the repository for review.
const CAPTURE_DIR = '../.local/captures';

test('test_release_first_run_asks_for_the_key_and_fits_the_viewport', async ({ page }, testInfo) => {
  await page.goto('/?mock_llm=missing');

  const field = page.getByLabel('API key');
  await expect(field).toBeVisible();
  await expect(page.getByRole('button', { name: '저장' })).toBeVisible();
  await expect(page.getByText('키는 이 컴퓨터의 OS 키 저장소에만 보관돼요.')).toBeVisible();

  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflows).toBe(false);

  const width = page.viewportSize()?.width ?? 0;
  await capture(page, testInfo, `${CAPTURE_DIR}/api-key-ko-${width}.png`);

  await field.fill('sk-test-key');
  await page.getByRole('button', { name: '저장' }).click();
  await expect(field).toBeHidden();
});
