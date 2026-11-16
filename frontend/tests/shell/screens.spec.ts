import { expect, test } from '@playwright/test';

import { capture } from '../support/capture';

const SCREENS = 'tests/screens';

/**
 * The evidence a screen change asks for: one capture per width, taken from the
 * mock answers so no user material leaves the machine. The files are tracked so
 * the pull request body can show them at the commit that made them.
 */
test('test_23_captures_the_first_screen_at_this_width', async ({ page }, testInfo) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '어떤 영상을 만들까요?' })).toBeVisible();
  await expect(page.locator('[data-slot="first-cards"] button')).toHaveCount(3);

  const width = page.viewportSize()?.width ?? 0;
  await capture(page, testInfo, `${SCREENS}/first-screen-${width}.png`, true);
});

test('test_23_captures_the_edit_screen_at_this_width', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' }).fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();
  await page.getByRole('button', { name: '단계 열기' }).click();
  await page.getByRole('menuitem', { name: '편집' }).click();
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();

  const width = page.viewportSize()?.width ?? 0;
  await capture(page, testInfo, `${SCREENS}/edit-${width}.png`, true);
});
