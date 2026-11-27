import { expect, test, type Page } from '@playwright/test';

async function openEdit(page: Page, prepare: string): Promise<void> {
  await page.goto(`/?mock_prepare=${prepare}`);
  await page
    .getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })
    .fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();
  const menu = page.getByRole('button', { name: '단계 열기' });
  if (await menu.isVisible()) {
    await menu.click();
    await page.getByRole('menuitem', { name: '편집', exact: true }).click();
  } else {
    await page
      .locator('[data-slot="stage-indicator"]')
      .getByRole('button', { name: '편집', exact: true })
      .click();
  }
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();
}

async function startVideo(page: Page): Promise<void> {
  await page.locator('[data-slot="top-bar"] [data-slot="next-action"]').click();
  await page
    .getByRole('dialog', { name: '장면 확인' })
    .getByRole('button', { name: '영상 만들기' })
    .click();
  // A check that finds nothing starts the making, so the press is the only confirm.
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();
  await expect(page.locator('[data-slot="top-bar"] .top-bar-status__trigger')).toBeVisible();
}

const ACTION = '[data-slot="top-bar"] [data-slot="next-action"]';
const PERCENT = '[data-slot="top-bar"] [data-slot="prepare-percent"]';

test('test_21_a_ready_install_shows_the_make_button_as_before', async ({ page }) => {
  await openEdit(page, 'ready');

  await expect(page.locator(ACTION)).toContainText('영상 만들기');
  await expect(page.locator('[data-slot="prepare-notice"]')).toHaveCount(0);
});

test('test_21_a_press_during_the_download_shows_the_percent_beside_the_stop_button', async ({ page }) => {
  await openEdit(page, 'downloading');
  await expect(page.locator(ACTION)).toBeEnabled();
  await expect(page.locator(ACTION)).toContainText('영상 만들기');

  await startVideo(page);

  await expect(page.locator(ACTION)).toContainText('만들기 멈추기');
  await expect(page.locator(PERCENT)).toContainText('준비 중 50%');
  await expect(page.locator('[data-slot="prepare-notice"]')).toHaveCount(0);
});

test('test_21_a_retrying_download_names_the_next_try_and_a_failed_one_offers_a_retry', async ({ page }) => {
  await openEdit(page, 'retrying');
  const notice = page.locator('[data-slot="prepare-notice"]');
  await expect(notice).toContainText('인터넷 연결이 끊겨서 음성 파일을 다시 받으려고 해요.');
  await expect(notice).toContainText('다음 시도');

  await openEdit(page, 'failed');
  await expect(notice).toContainText('음성 파일을 받지 못했어요');
  await page.getByRole('button', { name: '다시 시도' }).click();
  // The download moves again and the notice says so instead of going quiet.
  await expect(notice).toContainText('음성 파일을 다시 받는 중이에요.');
  await expect(page.getByRole('button', { name: '다시 시도' })).toHaveCount(0);
});

test('test_21_the_scene_check_says_the_voice_files_are_not_ready', async ({ page }) => {
  await openEdit(page, 'downloading');
  await page.locator(ACTION).click();
  const dialog = page.getByRole('dialog', { name: '장면 확인' });
  await expect(dialog).toContainText('음성 파일을 준비하는 중이에요');
  await expect(dialog.getByRole('button', { name: '영상 만들기' })).toBeEnabled();
  await page.keyboard.press('Escape');

  await openEdit(page, 'retrying');
  await page.locator(ACTION).click();
  await expect(dialog).toContainText('인터넷 연결이 끊겨서 음성 파일을 다시 받으려고 해요.');
});
