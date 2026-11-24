import { expect, test, type Page } from '@playwright/test';

import { capture } from '../support/capture';

const SCENE_COLUMN = '[data-slot="scene-column"]';
const SCENE_CARD = '[data-slot="scene-card"]';

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
  await expect(page.locator(`${SCENE_COLUMN} ${SCENE_CARD}`)).toHaveCount(5);
}

async function startVideo(page: Page): Promise<void> {
  await page.locator('[data-slot="next-action"]').click();
  await page
    .getByRole('dialog', { name: '장면 확인' })
    .getByRole('button', { name: '영상 만들기' })
    .click();
  await page.locator('[data-slot="export-start"]').click();
}

test('test_10a_the_edit_shell_shows_the_scenes_and_the_preview', async ({ page }) => {
  await openEdit(page);
  const column = page.locator(SCENE_COLUMN);
  await expect(column.locator(SCENE_CARD)).toHaveCount(5);
  await expect(page.locator('.video-preview')).toBeVisible();
  await expect(page.getByRole('heading', { name: '미리보기' })).toBeVisible();
  await expect(page.getByText('synthetic script')).toHaveCount(0);
  await expect(page.locator('[data-slot="top-bar"]').getByText('mp4 저장')).toHaveCount(0);

  const caption = page.getByRole('button', { name: '자막 저장' });
  await expect(caption).toBeVisible();
  await expect(caption).toBeDisabled();
  await page.locator('[data-slot="caption-save"]').hover();
  await expect(page.getByRole('tooltip')).toContainText('SRT');
});

test('test_23_the_preview_and_panel_padding_is_28_at_1280_and_1920', async ({ page }) => {
  await openEdit(page);
  for (const width of [1280, 1920]) {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 1080 });
    await page.waitForTimeout(200);
    const values = await page.evaluate(() => {
      const preview = document.querySelector<HTMLElement>('[data-slot="preview"]');
      const panel = document.querySelector<HTMLElement>('[data-slot="stage-panel"]');
      return {
        previewLeft: preview === null ? null : getComputedStyle(preview).paddingLeft,
        previewRight: preview === null ? null : getComputedStyle(preview).paddingRight,
        panelLeft: panel === null ? null : getComputedStyle(panel).paddingLeft,
        panelRight: panel === null ? null : getComputedStyle(panel).paddingRight,
      };
    });
    expect(values).toEqual({
      previewLeft: '28px',
      previewRight: '28px',
      panelLeft: '28px',
      panelRight: '28px',
    });
  }
});

test('test_23_the_scene_list_hides_the_scrollbar_and_shows_a_44_jump', async ({ page }) => {
  await openEdit(page);
  const viewport = page.locator(`${SCENE_COLUMN} .scroll-pane__viewport`);
  await expect(viewport).toBeVisible();
  expect(await viewport.evaluate((node) => getComputedStyle(node).scrollbarWidth)).toBe('none');
  const jump = page.locator(`${SCENE_COLUMN} .scroll-pane__jump .icon-button`);
  await expect(jump).toBeVisible();
  const box = await jump.boundingBox();
  expect(box).not.toBeNull();
  if (box === null) return;
  expect(Math.round(box.width)).toBe(44);
  expect(Math.round(box.height)).toBe(44);

  const chat = page.locator('[data-slot="edit-chat"] .scroll-pane__viewport');
  await expect(chat).toBeVisible();
  expect(await chat.evaluate((node) => getComputedStyle(node).scrollbarWidth)).toBe('none');
});

test('test_23_the_scene_card_shows_a_24_number_a_10_dot_and_the_length', async ({ page }) => {
  await openEdit(page);
  const card = page.locator(`${SCENE_COLUMN} ${SCENE_CARD}`).first();
  const number = await card.locator('.card__number').boundingBox();
  expect(number).not.toBeNull();
  if (number === null) return;
  expect(Math.round(number.width)).toBe(24);
  expect(Math.round(number.height)).toBe(24);
  await expect(card.locator('.card__duration')).toContainText('약');

  await page.getByRole('group', { name: '위치' }).getByRole('button', { name: '왼쪽 위' }).click();
  await expect(card.locator('[data-slot="scene-unseen"]')).toHaveCount(0);
});

test('test_23_the_position_menu_shows_nine_places', async ({ page }) => {
  await openEdit(page);
  const grid = page.getByRole('group', { name: '위치' });
  await expect(grid.getByRole('button')).toHaveCount(9);
  await expect(grid.getByRole('button', { name: '가운데 아래' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await grid.getByRole('button', { name: '오른쪽 위' }).click();
  await expect(grid.getByRole('button', { name: '오른쪽 위' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

test('test_10a_the_progress_window_is_480_and_closes_by_x_escape_and_outside', async ({ page }) => {
  await openEdit(page);
  await startVideo(page);
  const status = page.locator('.top-bar-status__trigger');
  await expect(status).toBeVisible({ timeout: 5000 });
  await status.click();
  const dialog = page.getByRole('dialog', { name: '영상을 만들고 있어요' });
  await expect(dialog).toBeVisible();
  await page.waitForTimeout(250);
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  if (box === null) return;
  expect(Math.round(box.width)).toBe(480);
  await expect(dialog.locator('[data-slot="progress-scene"]')).toHaveCount(5);
  await expect(dialog.getByRole('button')).toHaveCount(1);
  await expect(dialog.getByRole('button', { name: '멈추기' })).toHaveCount(0);
  await expect(dialog.locator('[data-slot="progress-close"]')).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await status.click();
  await expect(dialog).toBeVisible();
  await page.mouse.click(50, 500);
  await expect(dialog).toBeHidden();
  await status.click();
  await expect(dialog).toBeVisible();
  await dialog.locator('[data-slot="progress-close"]').click();
  await expect(dialog).toBeHidden();
  await expect(status).toBeFocused();
});

test('test_10a_the_top_bar_progress_is_blue_and_the_chevron_is_gray', async ({ page }) => {
  await openEdit(page);
  await startVideo(page);
  const status = page.locator('.top-bar-status__trigger');
  await expect(status).toBeVisible({ timeout: 5000 });
  const colours = await page.evaluate(() => {
    const label = document.querySelector<HTMLElement>('.top-bar-status__label');
    const chevron = document.querySelector<HTMLElement>('.top-bar-status__chevron');
    return {
      label: label === null ? null : getComputedStyle(label).color,
      chevron: chevron === null ? null : getComputedStyle(chevron).color,
      spinner: document.querySelector('.top-bar-status__icon .spinner') !== null,
    };
  });
  expect(colours).toEqual({
    label: 'rgb(27, 100, 218)',
    chevron: 'rgb(100, 107, 118)',
    spinner: true,
  });
});

test('test_10a_the_edit_screen_stays_usable_while_the_video_is_made', async ({ page }) => {
  await openEdit(page);
  await startVideo(page);
  await expect(page.locator('.top-bar-status__trigger')).toBeVisible({ timeout: 5000 });

  const grid = page.getByRole('group', { name: '위치' });
  await grid.getByRole('button', { name: '왼쪽 위' }).click();
  await expect(grid.getByRole('button', { name: '왼쪽 위' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );

  const viewport = page.locator(`${SCENE_COLUMN} .scroll-pane__viewport`);
  const jump = page.locator(`${SCENE_COLUMN} .scroll-pane__jump .icon-button`);
  await jump.click();
  await page.waitForTimeout(400);
  const scrolled = await viewport.evaluate((node) => node.scrollTop);
  expect(scrolled).toBeGreaterThan(0);

  await expect(page.locator('[data-slot="next-action"]')).toContainText('■');
  await expect(page.locator('[data-slot="next-action"]')).toContainText('만들기 멈추기');
  await page.locator('[data-slot="next-action"]').click();
  await expect(page.locator('[data-slot="next-action"]')).toContainText('영상 만들기');
});

test('test_10a_the_edit_composer_accepts_a_request_while_the_video_is_made', async ({ page }) => {
  await openEdit(page);
  await startVideo(page);
  await expect(page.locator('.top-bar-status__trigger')).toBeVisible({ timeout: 5000 });
  const composer = page.locator('[data-slot="conversation"] [data-slot="composer"]');
  const input = composer.locator('textarea');
  await expect(input).toBeEnabled();
  await input.fill('이 장면을 더 짧게');
  await composer.getByRole('button', { name: '보내기' }).click();
  await expect(page.locator('[data-slot="edit-chat"]')).toContainText('이 장면을 더 짧게');
  await expect(page.locator(`${SCENE_COLUMN} .scroll-pane__viewport`)).toBeVisible();
});

test('test_23_the_video_settings_panel_aligns_to_its_button_at_both_widths', async ({ page }) => {
  await openEdit(page);
  const trigger = page.locator('[data-slot="video-settings"]');
  const panel = page.locator('[data-slot="video-settings-panel"]');
  for (const width of [1280, 1920]) {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 1080 });
    await page.waitForTimeout(200);
    await trigger.click();
    await expect(panel).toBeVisible();
    const triggerBox = await trigger.boundingBox();
    const panelBox = await panel.boundingBox();
    expect(triggerBox).not.toBeNull();
    expect(panelBox).not.toBeNull();
    if (triggerBox === null || panelBox === null) return;
    expect(Math.abs(panelBox.x + panelBox.width - (triggerBox.x + triggerBox.width))).toBeLessThanOrEqual(1);
    await expect(page.locator('[data-slot="settings-scrim"]')).toBeVisible();
    await page.mouse.click(200, 500);
    await expect(panel).toBeHidden();
  }
});

test('test_23_reordering_with_the_buttons_shows_the_scope_and_keeps_the_arrow_size', async ({
  page,
}) => {
  await openEdit(page);
  const up = page.locator('.reorder-row').nth(0).getByRole('button', { name: /아래로 이동/ });
  await up.scrollIntoViewIfNeeded();
  const before = await up.boundingBox();
  const weight = await up.evaluate((node) => getComputedStyle(node).fontWeight);
  expect(before).not.toBeNull();
  if (before === null) return;
  await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2);
  await page.mouse.down();
  const pressed = await up.boundingBox();
  expect(pressed).not.toBeNull();
  if (pressed === null) return;
  expect(pressed.width).toBe(before.width);
  expect(pressed.height).toBe(before.height);
  expect(await up.evaluate((node) => getComputedStyle(node).fontWeight)).toBe(weight);
  await page.mouse.up();

  const dialog = page.getByRole('dialog', { name: '장면 순서를 바꿀까요?' });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[data-slot="order-compare"]')).toContainText('1. 훅');
  await expect(dialog.locator('[data-slot="order-compare"]')).toContainText('2. 첫 번째');
  await expect(dialog.locator('[data-slot="rebuild-scope"]')).toContainText('최종 영상을 다시 조립해요');
  await expect(dialog).toContainText('장면 흐름이 끊길 수 있어요');
  await expect(page.locator(`${SCENE_COLUMN} ${SCENE_CARD}`).first()).toContainText('훅');
  await dialog.getByRole('button', { name: '적용' }).click();
  await expect(page.locator(`${SCENE_COLUMN} ${SCENE_CARD}`).first()).toContainText('첫 번째');
});

test('test_10a_script_confirmation_starts_at_scene_one_but_regular_navigation_resumes', async ({ page }) => {
  await openEdit(page);
  const second = page.locator(`${SCENE_COLUMN} ${SCENE_CARD}`).nth(1).getByRole('button', {
    name: '첫 번째',
    exact: true,
  });
  await second.click();
  await expect(page.getByRole('heading', { name: '장면 2' })).toBeVisible();

  await openStage(page, '대본');
  const script = page.locator('[data-slot="stage-panel"][data-stage="script"]');
  await expect(script.locator('[data-slot="script-line-input"]').first()).toHaveValue('커피를 고르는 세 가지 기준');
  await expect(page.locator('[data-slot="top-bar"] [data-slot="next-action"]')).toHaveCount(0);
  await openStage(page, '편집');
  await expect(page.getByRole('heading', { name: '장면 2' })).toBeVisible();

  await openStage(page, '대본');
  await script.getByRole('button', { name: '이대로 영상 만들기' }).click();
  await expect(page.getByRole('heading', { name: '장면 1' })).toBeVisible();
  await expect(page.locator('[data-slot="stage-scroll"]')).toHaveJSProperty('scrollTop', 0);
});

test('test_10a_the_script_tone_is_decided_in_the_conversation', async ({ page }) => {
  await openEdit(page);
  await openStage(page, '대본');
  const script = page.locator('[data-slot="stage-panel"][data-stage="script"]');
  const input = script.locator('[data-slot="script-line-input"]').first();
  await input.fill('커피 맛을 천천히 봐요.');
  const tone = script.getByRole('combobox', { name: '말투' });
  const chat = page.locator('[data-slot="conversation"]');
  await tone.click();
  await page.getByRole('option', { name: '~합니다', exact: true }).click();
  await chat.getByRole('button', { name: '모두 취소' }).click();
  await expect(input).toHaveValue('커피 맛을 천천히 봐요.');

  await tone.click();
  await page.getByRole('option', { name: '~합니다', exact: true }).click();
  await chat.getByRole('button', { name: '모두 적용', exact: true }).click();
  await expect(script.locator('[data-slot="script-changed"]').first()).toHaveText('바뀜');
  await expect(input).toHaveValue('커피 맛을 천천히 봅니다.');
});

test('test_10a_the_edit_composer_has_no_example_chips', async ({ page }) => {
  await openEdit(page);
  const composer = page.locator('[data-slot="conversation"] [data-slot="composer"]');
  await expect(composer).toBeVisible();
  await expect(composer.locator('textarea')).toHaveAttribute('placeholder', '무엇을 바꿀까요?');
  await expect(composer.locator('[data-slot="composer-action"]')).toHaveCount(0);
  await expect(composer.locator('select')).toHaveCount(0);
});

test('test_23_the_sfx_picker_uses_the_shared_scroll_pane_and_stops_at_two', async ({ page }) => {
  await openEdit(page);
  const form = page.locator('[data-slot="scene-form"]');
  await form.getByRole('button', { name: '효과음 추가' }).click();
  const picker = page.getByRole('dialog', { name: '효과음 추가' });
  await expect(picker).toBeVisible();
  const viewport = picker.locator('.scroll-pane__viewport');
  expect(await viewport.evaluate((node) => getComputedStyle(node).scrollbarWidth)).toBe('none');
  const jump = picker.locator('.scroll-pane__jump .icon-button');
  await expect(jump).toBeVisible();
  // The dialog opens at a 0.98 scale, so measure the layout size, not the animated box.
  expect(await jump.evaluate((node) => (node as HTMLElement).offsetWidth)).toBe(44);
  await picker.getByRole('button', { name: '휙', exact: true }).click();

  await form.getByRole('button', { name: '효과음 추가' }).click();
  await page.getByRole('dialog', { name: '효과음 추가' }).getByRole('button', { name: '팝' }).click();
  await expect(form.getByRole('button', { name: '효과음 추가' })).toBeDisabled();
});

test('test_10a_a_closed_modal_returns_focus_to_its_trigger', async ({ page }) => {
  await openEdit(page);
  const action = page.locator('[data-slot="next-action"]');
  await action.click();
  await expect(page.getByRole('dialog', { name: '장면 확인' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: '장면 확인' })).toBeHidden();
  await expect(action).toBeFocused();
});

test('test_23_the_sidebar_offers_a_plus_and_the_new_name', async ({ page }) => {
  await openEdit(page);
  const button = page.getByRole('button', { name: '새로 만들기' });
  await expect(button).toBeVisible();
  await expect(button.locator('svg')).toHaveCount(1);
  await button.hover();
  await expect(page.getByRole('tooltip')).toContainText('새로 만들기');
});

test('test_23_the_edit_widths_match_the_approved_layout', async ({ page }, testInfo) => {
  await openEdit(page);
  for (const [width, height] of [[1280, 800], [1920, 1080]] as const) {
    await page.setViewportSize({ width, height });
    await page.waitForTimeout(200);
    const panel = await page.locator('[data-slot="stage-panel"]').boundingBox();
    const conversation = await page.locator('[data-slot="conversation"]').boundingBox();
    expect(panel).not.toBeNull();
    expect(conversation).not.toBeNull();
    if (panel === null || conversation === null) return;
    // The conversation face keeps the phone ratio of its height, a gap of 24 beside the rail.
    expect(Math.abs(conversation.width / conversation.height - 380 / 796)).toBeLessThan(0.005);
    expect(Math.round(conversation.x)).toBe(96);
    expect(Math.round(panel.width)).toBeGreaterThanOrEqual(340);
    if (testInfo.project.use.browserName === 'chromium') {
      const name = `edit-${width}.png`;
      const path = testInfo.outputPath(name);
      await capture(page, testInfo, path);
      await testInfo.attach(name, { path, contentType: 'image/png' });
    }
  }
});

test('test_10a_a_cleared_target_stays_cleared_after_a_field_change', async ({ page }) => {
  await openEdit(page);
  // The scene target chip sits above the input box, inside the conversation face.
  const composer = page.locator('[data-slot="conversation"]');
  await expect(composer.locator('[data-slot="composer-target"]')).toContainText('장면 1');
  await composer.getByRole('button', { name: '대상 지우기' }).click();
  await page.getByRole('group', { name: '위치' }).getByRole('button', { name: '오른쪽 위' }).click();
  await expect(page.getByRole('group', { name: '위치' }).getByRole('button', { name: '오른쪽 위' })).toHaveAttribute('aria-pressed', 'true');
  await expect(composer.locator('[data-slot="composer-target"]')).toHaveCount(0);
});

test('test_10a_the_scene_target_chip_can_be_cleared_and_sends', async ({ page }) => {
  await openEdit(page);
  const composer = page.locator('[data-slot="conversation"]');
  const input = composer.locator('textarea');
  await expect(composer.locator('[data-slot="composer-target"]')).toContainText('장면 1');
  await expect(input).toBeEnabled();
  await input.fill('이 장면을 더 짧게');
  await composer.getByRole('button', { name: '보내기' }).click();
  await expect(page.locator('[data-slot="edit-chat"]')).toContainText('바꿀 값이 없어요.', {
    timeout: 5000,
  });
  await composer.getByRole('button', { name: '대상 지우기' }).click();
  await expect(composer.locator('[data-slot="composer-target"]')).toHaveCount(0);
});

test('test_10a_the_top_bar_stop_works_from_the_open_progress_window', async ({ page }) => {
  await openEdit(page);
  await startVideo(page);
  const status = page.locator('.top-bar-status__trigger');
  await expect(status).toBeVisible({ timeout: 5000 });
  await status.click();
  await expect(page.getByRole('dialog', { name: '영상을 만들고 있어요' })).toBeVisible();
  await page.locator('[data-slot="next-action"]').click();
  await expect(page.locator('[data-slot="next-action"]')).toContainText('영상 만들기');
});
