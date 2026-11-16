import { expect, test, type Page } from '@playwright/test';

const SIDEBAR = 72;
const SENTENCE = '커피를 고르는 세 가지 기준';

async function startVideo(page: Page): Promise<void> {
  await page.getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' }).fill(SENTENCE);
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();
}

test('test_10a_first_screen_is_named_by_one_column_beside_the_sidebar', async ({ page }) => {
  await page.goto('/');
  const column = page.locator('[data-slot="first-screen"] > div');
  await expect(column).toBeVisible();

  const width = page.viewportSize()?.width ?? 0;
  test.skip(width !== 1920, 'the desktop column is measured at 1920px');

  const box = await column.boundingBox();
  expect(box).not.toBeNull();
  if (box === null) return;

  expect(Math.abs(box.x + box.width / 2 - (SIDEBAR + (width - SIDEBAR) / 2))).toBeLessThanOrEqual(2);
});

test('test_10a_the_input_cards_and_recent_projects_share_their_edges', async ({ page }) => {
  await page.goto('/');
  const composer = await page.locator('[data-slot="first-screen"] [data-slot="composer"]').boundingBox();
  const cards = await page.locator('[data-slot="first-cards"]').boundingBox();
  const recent = await page.locator('[data-slot="first-recent"]').boundingBox();
  expect(composer).not.toBeNull();
  expect(cards).not.toBeNull();
  expect(recent).not.toBeNull();
  if (composer === null || cards === null || recent === null) return;

  for (const part of [cards, recent]) {
    expect(Math.abs(part.x - composer.x)).toBeLessThanOrEqual(1);
    expect(Math.abs(part.width - composer.width)).toBeLessThanOrEqual(1);
  }
});

test('test_10a_the_first_screen_has_no_step_indicator', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-slot="first-screen"]')).toBeVisible();

  await expect(page.locator('[data-slot="stage-indicator"]')).toHaveCount(0);
  await expect(page.locator('[data-slot="stage-menu"]')).toHaveCount(0);
  await expect(page.locator('[data-slot="next-action"]')).toHaveCount(0);
});

test('test_10a_the_sidebar_names_an_icon_on_hover', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '새 영상' }).hover();

  await expect(page.getByRole('tooltip')).toContainText('새 영상');
});

test('test_23_the_first_screen_does_not_scroll_sideways', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '어떤 영상을 만들까요?' })).toBeVisible();

  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflows).toBe(false);
});

test('test_23_a_sentence_starts_a_video_from_the_mock_answers', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /만약 ~라면/ }).click();
  await expect(page.getByText('카드: 만약 ~라면?')).toBeVisible();

  await startVideo(page);

  await expect(page.getByText('차례를 기다리는 중이에요.', { exact: true })).toBeVisible();
  await expect(page.locator('main[data-screen="app"]')).toBeVisible();
});
