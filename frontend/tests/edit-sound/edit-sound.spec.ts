import { expect, test, type Locator, type Page } from '@playwright/test';

const WIDTHS = [
  { width: 1280, height: 800 },
  { width: 1920, height: 1080 },
] as const;

async function openStage(page: Page, label: string): Promise<void> {
  const menu = page.getByRole('button', { name: '단계 열기' });
  if (await menu.isVisible()) {
    await menu.click();
    await page.getByRole('menuitem', { name: label, exact: true }).click();
  } else {
    await page
      .locator('[data-slot="stage-indicator"]')
      .getByRole('button', { name: label, exact: true })
      .click();
  }
}

async function openEdit(page: Page): Promise<void> {
  await page.goto('/');
  await page
    .getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })
    .fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();
  await openStage(page, '편집');
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();
}

async function openTab(page: Page, name: '소리' | '자막' | '장면'): Promise<void> {
  await page.getByRole('tab', { name, exact: true }).click();
}

async function expectHiddenScrollbar(viewport: Locator): Promise<void> {
  await expect(viewport).toBeVisible();
  expect(await viewport.evaluate((node) => getComputedStyle(node).scrollbarWidth)).toBe('none');
}

async function expectJump(jump: Locator): Promise<void> {
  await expect(jump).toBeVisible();
  const box = await jump.boundingBox();
  expect(box).not.toBeNull();
  if (box === null) return;
  expect(Math.round(box.width)).toBe(44);
  expect(Math.round(box.height)).toBe(44);
}

test('test_14_the_sound_tab_fits_the_panel_at_1280_and_1920', async ({ page }) => {
  await openEdit(page);
  await openTab(page, '소리');
  const tab = page.locator('[data-slot="sound-tab"]');
  await expect(tab).toBeVisible();
  for (const size of WIDTHS) {
    await page.setViewportSize(size);
    await page.waitForTimeout(200);
    const overflow = await tab.evaluate((node) => {
      const viewport = node.closest('.scroll-pane__viewport');
      return viewport === null ? -1 : viewport.scrollWidth - viewport.clientWidth;
    });
    expect(overflow).toBeLessThanOrEqual(0);
    await expect(page.getByRole('switch', { name: 'BGM 켜기' })).toHaveAttribute('aria-checked', 'true');
    await expect(page.getByRole('combobox', { name: '분위기' })).toBeVisible();
    await expect(page.getByRole('combobox', { name: '크기' })).toBeVisible();
  }
});

test('test_9_the_voice_list_hides_the_scrollbar_and_shows_a_44_jump', async ({ page }) => {
  await openEdit(page);
  await openTab(page, '소리');
  for (const size of WIDTHS) {
    await page.setViewportSize(size);
    await page.locator('[data-slot="voice-change"]').click();
    const dialog = page.getByRole('dialog', { name: '목소리 고르기' });
    await expect(dialog).toBeVisible();
    const viewport = dialog.locator('.scroll-pane__viewport');
    await expectHiddenScrollbar(viewport);
    await expectJump(dialog.locator('.scroll-pane__jump .icon-button'));
    await dialog.getByRole('button', { name: '취소' }).click();
    await expect(dialog).toBeHidden();
  }
});

test('test_9_the_voice_listen_and_pick_buttons_are_separate', async ({ page }) => {
  await openEdit(page);
  await openTab(page, '소리');
  await page.locator('[data-slot="voice-change"]').click();
  const dialog = page.getByRole('dialog', { name: '목소리 고르기' });
  await dialog.getByRole('button', { name: '소희 (한국어) 듣기', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '소희 (한국어) 듣기 멈추기' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: '적용' })).toBeDisabled();
  await dialog.getByRole('button', { name: '소희 (한국어)', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '적용' })).toBeEnabled();
  await dialog.getByRole('button', { name: '적용' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator('[data-slot="voice-section"] .tag__label')).toHaveText('소희 (한국어)');
});

test('test_9_the_sound_effect_window_uses_its_height_at_1280_and_1920', async ({ page }) => {
  await openEdit(page);
  for (const size of WIDTHS) {
    await page.setViewportSize(size);
    await page.getByRole('button', { name: '효과음 추가' }).click();
    const dialog = page.getByRole('dialog', { name: '효과음 추가' });
    await expect(dialog).toBeVisible();
    const pane = dialog.locator('.scroll-pane');
    await expectHiddenScrollbar(dialog.locator('.scroll-pane__viewport'));
    await expectJump(dialog.locator('.scroll-pane__jump .icon-button'));
    const box = await pane.boundingBox();
    expect(box).not.toBeNull();
    if (box !== null) expect(Math.round(box.height)).toBe(288);
    await expect(dialog.locator('.scroll-pane__viewport button')).toHaveCount(12);
    await dialog.getByRole('button', { name: '닫기' }).first().click();
    await expect(dialog).toBeHidden();
  }
});

test('test_14_an_upload_that_is_not_audio_shows_an_error', async ({ page }) => {
  await openEdit(page);
  await openTab(page, '소리');
  await page
    .locator('[data-slot="composer"]')
    .filter({ visible: true })
    .locator('[data-slot="composer-file"][data-kind="bgm"]')
    .setInputFiles({
      name: 'notes.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('not audio'),
    });
  await expect(page.locator('[data-slot="bgm-upload-error"]:visible')).toContainText('오디오 파일만 올릴 수 있어요.');
});

test('test_14_an_uploaded_track_becomes_the_picked_track', async ({ page }) => {
  await openEdit(page);
  await openTab(page, '소리');
  await page.locator('[data-slot="composer-plus"]').getByRole('button').click();
  const chooseFile = page.waitForEvent('filechooser');
  await page.getByRole('menuitem', { name: 'BGM 올리기' }).click();
  await (await chooseFile).setFiles({
    name: 'mine.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('RIFF'),
  });
  await expect(page.locator('[data-slot="bgm-section"] .tag__label')).toHaveText('올린 BGM 1', {
    timeout: 5000,
  });
});

test('test_14_the_bgm_level_has_three_choices', async ({ page }) => {
  await openEdit(page);
  await openTab(page, '소리');
  await page.getByRole('combobox', { name: '크기' }).click();
  await expect(page.getByRole('option')).toHaveCount(3);
});

test('test_24_the_caption_tab_picks_a_mode_and_a_position_and_keeps_them_across_tabs', async ({ page }) => {
  await openEdit(page);
  await openTab(page, '자막');
  const group = page.getByRole('radiogroup', { name: '자막 방식' });
  await expect(group.getByRole('radio')).toHaveCount(3);
  await group.getByRole('radio', { name: '구절형' }).click();
  await page.getByRole('combobox', { name: '자막 위치' }).click();
  await expect(page.getByRole('option')).toHaveCount(5);
  await page.getByRole('option', { name: '위쪽' }).click();
  await expect(page.getByRole('combobox', { name: '자막 위치' })).toContainText('위쪽');
  await openTab(page, '소리');
  await expect(page.locator('[data-slot="sound-tab"]')).toBeVisible();
  await openTab(page, '자막');
  await expect(group.getByRole('radio', { name: '구절형' })).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByRole('combobox', { name: '자막 위치' })).toContainText('위쪽');
});
