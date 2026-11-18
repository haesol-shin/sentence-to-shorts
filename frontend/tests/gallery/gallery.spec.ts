import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type Frame, type Page } from '@playwright/test';

import { galleryParts, inlineCases, portalCases } from '../../src/gallery/items';

const GALLERY = '/src/gallery/index.html';
const PROBE = `${GALLERY}?probe=1`;
const SHOTS = process.env.GALLERY_SHOTS_DIR ?? join(process.cwd(), 'test-results', 'gallery-shots');

test.describe.configure({ mode: 'serial', timeout: 180_000 });

// eslint-disable-next-line no-empty-pattern
test.beforeEach(({}, testInfo) => {
  test.skip(
    testInfo.project.name !== 'chromium-desktop',
    'the gallery evidence runs once in chromium; the app suite owns the other browsers',
  );
});

async function galleryReady(page: Page, partId?: string, batch = 1): Promise<void> {
  const query =
    partId === undefined
      ? `?batch=${batch}&view=all`
      : `?batch=${batch}&view=all&part=${encodeURIComponent(partId)}`;
  const expected = galleryParts.filter((part) => part.batch === batch).length;
  await page.goto(`${GALLERY}${query}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.waitForFunction(
    (count) => document.querySelectorAll('[data-part]').length === count,
    partId === undefined ? expected : 1,
    { timeout: 120_000 },
  );
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll('iframe[data-frame-part]')].every(
        (frame) => frame instanceof HTMLIFrameElement && frame.contentDocument?.readyState === 'complete',
      ),
    undefined,
    { timeout: 120_000 },
  );
  await page.waitForTimeout(400);
}

async function frameOf(page: Page, selector: string): Promise<Frame> {
  const handle = await page.locator(selector).elementHandle();
  if (handle === null) throw new Error(`missing frame: ${selector}`);
  const frame = await handle.contentFrame();
  if (frame === null) throw new Error(`missing content: ${selector}`);
  return frame;
}

function labelOf(partId: string, slug: string): string {
  const part = galleryParts.find((candidate) => candidate.id === partId);
  const entry = part?.cases.find((candidate) => candidate.slug === slug);
  if (entry === undefined) throw new Error(`missing case: ${partId} ${slug}`);
  return entry.label;
}

test('test_10a_gallery_lists_every_part_and_numbered_case_in_order', async ({ page }) => {
  for (const batch of [1, 2, 3] as const) {
    await galleryReady(page, undefined, batch);
    const batchParts = galleryParts.filter((part) => part.batch === batch);

    const ids = await page
      .locator('[data-part]')
      .evaluateAll((elements) => elements.map((element) => element.getAttribute('data-part')));
    expect(ids).toEqual(batchParts.map((part) => part.id));

    for (const part of batchParts) {
      if (inlineCases(part).length > 0) {
        const frame = await frameOf(page, `iframe[data-frame-group="${part.id}"][width="390"]`);
        const labels = await frame
          .locator('[data-case]')
          .evaluateAll((elements) => elements.map((element) => element.getAttribute('data-case')));
        expect(labels).toEqual(inlineCases(part).map((entry) => entry.label));
      }
      for (const entry of portalCases(part)) {
        const frame = await frameOf(page, `iframe[data-frame-case="${entry.label}"][width="390"]`);
        await expect(frame.locator(`[data-case="${entry.label}"]`)).toHaveCount(1);
        await expect(
          frame
            .locator('[role=menu], [role=listbox], [role=tooltip], [role=dialog], [role=alertdialog], [role=status]')
            .first(),
        ).toBeVisible({ timeout: 10_000 });
      }
    }
  }
});

test('test_10a_visible_box_stays_equal_across_states', async ({ page }) => {
  const sizesOf = async (
    partId: string,
    labels: readonly string[],
    selector: string,
  ): Promise<[number, number][]> => {
    await galleryReady(page, partId);
    const frame = await frameOf(page, `iframe[data-frame-group="${partId}"][width="390"]`);
    const sizes: [number, number][] = [];
    for (const label of labels) {
      const size = await frame
        .locator(`[data-case="${label}"] ${selector}`)
        .first()
        .evaluate((element) => {
          const box = element.getBoundingClientRect();
          return [box.width, box.height];
        });
      sizes.push([Math.round(size[0] * 10) / 10, Math.round(size[1] * 10) / 10]);
    }
    return sizes;
  };
  const equal = (sizes: [number, number][]) =>
    expect(new Set(sizes.map(([width, height]) => `${width}x${height}`)).size).toBe(1);

  equal(
    await sizesOf(
      'button-primary',
      ['1-1-default', '1-2-hover', '1-3-pressed', '1-4-disabled', '1-5-loading', '1-6-focus-visible'],
      'button',
    ),
  );
  const chip = await sizesOf('chip', ['6-1-default'], '.chip');
  expect(chip[0][1]).toBe(36);
  equal(await sizesOf('chip', ['6-1-default', '6-2-loading', '6-3-error', '6-4-focus-visible'], '.chip'));
  equal(await sizesOf('chip', ['6-5-no-lead', '6-6-no-lead-loading'], '.chip'));
  equal(await sizesOf('chip', ['6-7-element-default', '6-8-element-error'], '.chip'));
  equal(
    await sizesOf(
      'tabs',
      ['10-1-default', '10-2-hover', '10-3-pressed', '10-4-selected', '10-5-disabled', '10-6-focus-visible'],
      '[role=tab]',
    ),
  );
  equal(await sizesOf('tabs', ['10-7-latin-default', '10-8-latin-selected'], '[role=tab]'));
  equal(
    await sizesOf(
      'switch',
      ['12-1-default', '12-2-hover', '12-3-pressed', '12-4-selected', '12-5-disabled', '12-6-focus-visible'],
      '.switch-option',
    ),
  );
  equal(await sizesOf('switch', ['12-4-selected', '12-7-label-element'], '.switch-option'));
});

test('test_10a_batch_two_boxes_stay_equal_across_states', async ({ page }) => {
  const sizesOf = async (
    partId: string,
    labels: readonly string[],
    selector: string,
  ): Promise<[number, number][]> => {
    await galleryReady(page, partId, 2);
    const frame = await frameOf(page, `iframe[data-frame-group="${partId}"][width="390"]`);
    const sizes: [number, number][] = [];
    for (const label of labels) {
      const size = await frame
        .locator(`[data-case="${label}"] ${selector}`)
        .first()
        .evaluate((element) => {
          const box = element.getBoundingClientRect();
          return [box.width, box.height];
        });
      sizes.push([Math.round(size[0] * 10) / 10, Math.round(size[1] * 10) / 10]);
    }
    return sizes;
  };
  const equal = (sizes: [number, number][]) =>
    expect(new Set(sizes.map(([width, height]) => `${width}x${height}`)).size).toBe(1);

  equal(
    await sizesOf(
      'send-button',
      ['17-1-default', '17-2-hover', '17-3-pressed', '17-4-disabled', '17-5-loading', '17-6-focus-visible'],
      'button',
    ),
  );
  const send = await sizesOf('send-button', ['17-1-default'], 'button');
  expect(send[0]).toEqual([32, 32]);

  equal(
    await sizesOf('file-chip', ['19-1-default', '19-2-loading', '19-3-error', '19-4-focus-visible', '19-5-error-retry'], '.file-chip'),
  );
  const fileChip = await sizesOf('file-chip', ['19-1-default'], '.file-chip');
  expect(fileChip[0][1]).toBe(56);
  expect(fileChip[0][0]).toBeLessThanOrEqual(320);

  await galleryReady(page, 'dialog', 2);
  for (const width of [390, 1920] as const) {
    const widths: number[] = [];
    for (const label of ['21-1-default', '21-2-long']) {
      const frame = await frameOf(page, `iframe[data-frame-case="${label}"][width="${width}"]`);
      const box = await frame.locator('.dialog').evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width;
      });
      widths.push(Math.round(box));
    }
    expect(new Set(widths).size).toBe(1);
    expect(widths[0]).toBe(width === 390 ? 342 : 480);
  }
});

test('test_10a_toast_drop_zone_progress_and_composer_name_their_role', async ({ page }) => {
  await galleryReady(page, 'toast', 2);
  const toast = await frameOf(page, 'iframe[data-frame-case="25-1-default"][width="390"]');
  await expect(toast.getByRole('status')).toHaveText('대본을 저장했어요');
  const toastBox = await toast.locator('.toast-surface').evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return { height: rect.height, radius: style.borderRadius };
  });
  expect(toastBox.height).toBe(44);
  expect(toastBox.radius).toBe('22px');

  await galleryReady(page, 'file-drop', 2);
  const drop = await frameOf(page, 'iframe[data-frame-case="20-1-default"][width="390"]');
  await expect(drop.getByRole('status')).toContainText('여기에 놓으면 올라가요');
  const border = await drop.locator('.file-drop__frame').evaluate((element) => {
    const style = getComputedStyle(element);
    return { style: style.borderTopStyle, width: style.borderTopWidth, inset: style.inset };
  });
  expect(border.style).toBe('dashed');
  expect(border.width).toBe('1px');

  await galleryReady(page, 'progress', 2);
  const progress = await frameOf(page, 'iframe[data-frame-group="progress"][width="390"]');
  await expect(progress.locator('[data-case="27-2-label"] [role=progressbar]')).toHaveAttribute(
    'aria-valuenow',
    '40',
  );
  await expect(progress.locator('[data-case="27-2-label"]')).toContainText('40%');

  await galleryReady(page, 'composer', 2);
  const composer = await frameOf(page, 'iframe[data-frame-group="composer"][width="390"]');
  await expect(
    composer.locator('[data-case="18-1-default"]').getByRole('textbox', { name: '메시지 입력' }),
  ).toBeVisible();
  await expect(composer.locator('[data-case="18-1-default"] button')).toHaveCount(2);
});

test('test_10a_dialog_and_sheet_report_open_state_and_return_focus', async ({ page }) => {
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });

  const dialogTrigger = page.locator('[data-probe="dialog"] button').first();
  await expect(dialogTrigger).toHaveAttribute('aria-expanded', 'false');
  await dialogTrigger.click();
  await expect(page.getByRole('dialog').first()).toBeVisible();
  await expect(dialogTrigger).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(dialogTrigger).toHaveAttribute('aria-expanded', 'false');
  await expect(dialogTrigger).toBeFocused();

  const sheetTrigger = page.locator('[data-probe="sheet"] button').first();
  await expect(sheetTrigger).toHaveAttribute('aria-expanded', 'false');
  await sheetTrigger.click();
  await expect(page.getByRole('dialog', { name: '목소리 고르기' })).toBeVisible();
  await expect(sheetTrigger).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(sheetTrigger).toHaveAttribute('aria-expanded', 'false');
  await expect(sheetTrigger).toBeFocused();
});

test('test_10a_nested_window_controls_stay_above_the_dialog', async ({ page }) => {
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-probe="dialog-nested"] button').first().click();
  const dialog = page.getByRole('dialog', { name: '중첩 조작' });
  await expect(dialog).toBeVisible();

  await dialog.getByRole('button', { name: '파일 넣기' }).click();
  await expect(page.getByRole('menu')).toBeVisible();
  const menuOnTop = await page.getByRole('menu').evaluate((element) => {
    const box = element.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return hit !== null && element.contains(hit);
  });
  expect(menuOnTop).toBe(true);
  await page.getByRole('menuitem', { name: '참고 영상 올리기' }).click();
  await expect(page.locator('[data-probe="log"]')).toHaveText('nested-menu:upload');

  await dialog.getByRole('combobox', { name: '목소리' }).click();
  await expect(page.getByRole('listbox')).toBeVisible();
  const option = page.getByRole('option', { name: '차분한 목소리' });
  const optionOnTop = await option.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return hit !== null && element.contains(hit);
  });
  expect(optionOnTop).toBe(true);
  await option.click();
  await expect(page.locator('[data-probe="log"]')).toHaveText('nested-select:calm');

  await dialog.getByRole('button', { name: '이유 보기' }).hover();
  const tooltip = page.getByRole('tooltip');
  await expect(tooltip).toBeVisible();
  const tooltipOnTop = await tooltip.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return hit !== null && element.contains(hit);
  });
  expect(tooltipOnTop).toBe(true);

  await dialog.getByRole('button', { name: '닫기' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('test_10a_dialog_and_sheet_end_motion_immediately_when_reduced', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });

  const durations = async (triggerSelector: string, dialogName?: string) => {
    await page.locator(triggerSelector).first().click();
    const dialog = dialogName === undefined ? page.getByRole('dialog').first() : page.getByRole('dialog', { name: dialogName });
    await expect(dialog).toBeVisible();
    const value = await dialog.evaluate((element) => getComputedStyle(element).transitionDuration);
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    return value;
  };

  const dialogDuration = await durations('[data-probe="dialog"] button');
  expect(dialogDuration.split(',').every((value) => value.trim() === '0s')).toBe(true);

  const sheetDuration = await durations('[data-probe="sheet"] button', '목소리 고르기');
  expect(sheetDuration.split(',').every((value) => value.trim() === '0s')).toBe(true);
});

test('test_10a_tabs_radio_and_switch_change_with_the_keyboard', async ({ page }) => {
  await galleryReady(page, 'tabs');
  const tabs = await frameOf(page, 'iframe[data-frame-group="tabs"][width="390"]');
  const firstTab = tabs.locator('[data-case="10-1-default"] [role=tab]').first();
  await firstTab.focus();
  await firstTab.press('ArrowRight');
  await page.keyboard.press('Enter');
  await expect(
    tabs.locator('[data-case="10-1-default"] [role=tab]').nth(1),
  ).toHaveAttribute('aria-selected', 'true');

  await galleryReady(page, 'radio');
  const radio = await frameOf(page, 'iframe[data-frame-group="radio"][width="390"]');
  const firstRadio = radio.locator('[data-case="11-1-default"] [role=radio]').first();
  await firstRadio.focus();
  await firstRadio.press('ArrowRight');
  await expect(
    radio.locator('[data-case="11-1-default"] [role=radio]').nth(1),
  ).toHaveAttribute('aria-checked', 'true');

  await galleryReady(page, 'switch');
  const toggle = await frameOf(page, 'iframe[data-frame-group="switch"][width="390"]');
  const switchControl = toggle.locator('[data-case="12-1-default"] [role=switch]');
  await switchControl.focus();
  await expect(switchControl).toHaveAttribute('aria-checked', 'false');
  await switchControl.press('Space');
  await expect(switchControl).toHaveAttribute('aria-checked', 'true');
});

test('test_10a_menu_and_select_report_open_state_and_return_focus_on_escape', async ({ page }) => {
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });

  const menuTrigger = page.locator('[data-probe="menu"] button').first();
  await expect(menuTrigger).toHaveAttribute('aria-expanded', 'false');
  await menuTrigger.click();
  await expect(page.getByRole('menu')).toBeVisible();
  await expect(menuTrigger).toHaveAttribute('aria-expanded', 'true');
  await expect(menuTrigger).toHaveAttribute('data-popup-open', '');
  await expect(page.getByRole('menu')).toHaveAttribute('data-open', '');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toHaveCount(0);
  await expect(menuTrigger).toHaveAttribute('aria-expanded', 'false');
  await expect(menuTrigger).toBeFocused();
  await expect(page.locator('[role=menuitem]')).toHaveCount(0);

  const selectTrigger = page.locator('[data-probe="select"] [role=combobox]');
  await expect(selectTrigger).toHaveAttribute('aria-expanded', 'false');
  await selectTrigger.click();
  await expect(page.getByRole('listbox')).toBeVisible();
  await expect(selectTrigger).toHaveAttribute('aria-expanded', 'true');
  await expect(selectTrigger).toHaveAttribute('data-popup-open', '');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('listbox')).toBeHidden();
  await expect(selectTrigger).toHaveAttribute('aria-expanded', 'false');
  await expect(selectTrigger).toBeFocused();
  await expect(page.locator('[role=option]:visible')).toHaveCount(0);
  for (let step = 0; step < 6; step += 1) {
    await page.keyboard.press('Tab');
    const role = await page.evaluate(() => document.activeElement?.getAttribute('role'));
    expect(role).not.toBe('option');
  }
});

test('test_10a_menu_and_select_can_be_used_with_the_keyboard', async ({ page }) => {
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });

  const menuTrigger = page.locator('[data-probe="menu"] button').first();
  await menuTrigger.focus();
  await menuTrigger.press('Enter');
  await expect(page.getByRole('menu')).toBeVisible();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(page.locator('[data-probe="log"]')).toHaveText('menu:link');

  const selectTrigger = page.locator('[data-probe="select"] [role=combobox]');
  await selectTrigger.focus();
  await selectTrigger.press('Enter');
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(page.locator('[data-probe="log"]')).toHaveText('select:calm');
});

test('test_10a_tooltip_opens_on_hover_and_keyboard_focus', async ({ page }) => {
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });
  const trigger = page.locator('[data-probe="tooltip"] button').first();

  await trigger.hover();
  const tooltip = page.getByRole('tooltip');
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toHaveAttribute('data-open', '');
  const describedBy = await trigger.getAttribute('aria-describedby');
  expect(describedBy).not.toBeNull();
  expect(await tooltip.getAttribute('id')).toBe(describedBy);

  await page.mouse.move(4, 4);
  await expect(page.getByRole('tooltip')).toHaveCount(0);

  await trigger.focus();
  await expect(page.getByRole('tooltip')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
});

test('test_10a_unavailable_menu_row_shows_its_reason_on_hover', async ({ page }) => {
  await galleryReady(page, 'menu');
  const frame = await frameOf(page, 'iframe[data-frame-case="13-12-item-unavailable"][width="390"]');
  const row = frame.locator('[role=menuitem][aria-disabled=true]').first();
  await row.hover();
  const tooltip = frame.getByRole('tooltip');
  await expect(tooltip).toBeVisible();
  expect(await tooltip.textContent()).toContain('곧 지원 항목은 다음 단계에서 열려요.');
  const describedBy = (await row.getAttribute('aria-describedby')) ?? '';
  expect(describedBy.split(' ')).toContain(await tooltip.getAttribute('id'));
  const onTop = await tooltip.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return hit !== null && element.contains(hit);
  });
  expect(onTop).toBe(true);
});

test('test_10a_heading_menu_keeps_half_a_row_at_the_scroll_end', async ({ page }) => {
  await galleryReady(page, 'menu');
  const frame = await frameOf(page, 'iframe[data-frame-case="13-14-open-long"][width="390"]');
  await expect(frame.locator('.scroll-fade')).toHaveAttribute('data-fade', 'bottom');
  const geometry = await frame.locator('.menu-scroll').evaluate((element) => {
    const rows = [...element.querySelectorAll<HTMLElement>('.menu-item')];
    const box = element.getBoundingClientRect();
    const first = rows[0].getBoundingClientRect();
    const second = rows[1].getBoundingClientRect();
    const origin = first.top - box.top + element.scrollTop;
    const pitch = second.top - first.top;
    return {
      pitch,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      remainder: (element.clientHeight - origin) % pitch,
    };
  });
  expect(geometry.scrollHeight).toBeGreaterThan(geometry.clientHeight);
  expect(Math.abs(geometry.remainder - geometry.pitch / 2)).toBeLessThan(1.5);
});

test('test_10a_loading_button_keeps_its_accessible_name', async ({ page }) => {
  await galleryReady(page, 'button-primary');
  const frame = await frameOf(page, 'iframe[data-frame-group="button-primary"][width="390"]');
  const button = frame.locator('[data-case="1-5-loading"] button');
  await expect(button).toHaveAccessibleName('영상 만들기');
});

test('test_10a_keyboard_focus_draws_the_token_ring', async ({ page }) => {
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });
  await page.locator('body').click({ position: { x: 4, y: 4 } });
  await page.keyboard.press('Tab');

  const ring = await page.evaluate(() => {
    const element = document.activeElement;
    if (element === null) return null;
    const style = getComputedStyle(element);
    return {
      tag: element.tagName,
      outlineWidth: style.outlineWidth,
      outlineStyle: style.outlineStyle,
      outlineColor: style.outlineColor,
    };
  });

  expect(ring).not.toBeNull();
  expect(ring?.outlineStyle).not.toBe('none');
  expect(Number.parseFloat(ring?.outlineWidth ?? '0')).toBeGreaterThanOrEqual(2);
});

test('test_10a_reduced_motion_ends_panel_motion_immediately', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-probe="select"] [role=combobox]').click();
  await expect(page.getByRole('listbox')).toBeVisible();

  const motion = await page.evaluate(() => {
    const menu = document.querySelector('.field-menu');
    const icon = document.querySelector('.field-trigger__icon');
    return {
      token: getComputedStyle(document.documentElement).getPropertyValue('--motion-panel-duration').trim(),
      menuDuration: menu === null ? '' : getComputedStyle(menu).transitionDuration,
      iconDuration: icon === null ? '' : getComputedStyle(icon).transitionDuration,
      iconTransform: icon === null ? '' : getComputedStyle(icon).transform,
    };
  });

  expect(motion.token).toBe('0ms');
  expect(motion.menuDuration.split(',').every((value) => value.trim() === '0s')).toBe(true);
  expect(motion.iconDuration.split(',').every((value) => value.trim() === '0s')).toBe(true);
  expect(motion.iconTransform).not.toBe('none');

  await page.keyboard.press('Escape');
  await expect(page.getByRole('listbox')).toHaveCount(0);
});

test('test_10a_select_opens_below_and_flips_above_only_when_space_is_short', async ({ page }) => {
  await galleryReady(page, 'value-field');
  const records: unknown[] = [];

  for (const width of [390, 1920] as const) {
    const below = await frameOf(page, `iframe[data-frame-case="14-4-open"][width="${width}"]`);
    await below.locator('[role=listbox]').waitFor();
    const belowBox = await below.evaluate(() => {
      const rect = (selector: string) => {
        const element = document.querySelector(selector);
        if (element === null) return null;
        const box = element.getBoundingClientRect();
        return { left: box.left, top: box.top, right: box.right, bottom: box.bottom, width: box.width, height: box.height };
      };
      const items = [...document.querySelectorAll('[role=option]')].map((element) => {
        const box = element.getBoundingClientRect();
        return { top: box.top, bottom: box.bottom };
      });
      return { trigger: rect('.field-trigger'), popup: rect('.field-menu'), items, viewport: innerHeight };
    });
    expect(belowBox.popup).not.toBeNull();
    expect(belowBox.trigger).not.toBeNull();
    expect(belowBox.popup?.top ?? 0).toBeGreaterThanOrEqual((belowBox.trigger?.bottom ?? 0) - 1);
    expect(belowBox.popup?.width ?? 0).toBeCloseTo(belowBox.trigger?.width ?? 0, 0);

    const above = await frameOf(page, `iframe[data-frame-case="14-5-open-above"][width="${width}"]`);
    await above.locator('[role=listbox]').waitFor();
    const aboveBox = await above.evaluate(() => {
      const rect = (selector: string) => {
        const element = document.querySelector(selector);
        if (element === null) return null;
        const box = element.getBoundingClientRect();
        return { left: box.left, top: box.top, right: box.right, bottom: box.bottom, width: box.width, height: box.height };
      };
      const items = [...document.querySelectorAll('[role=option]')].map((element) => {
        const box = element.getBoundingClientRect();
        return { top: box.top, bottom: box.bottom };
      });
      return { trigger: rect('.field-trigger'), popup: rect('.field-menu'), items, viewport: innerHeight };
    });
    expect(aboveBox.popup).not.toBeNull();
    expect(aboveBox.trigger).not.toBeNull();
    expect(aboveBox.popup?.bottom ?? 0).toBeLessThanOrEqual((aboveBox.trigger?.top ?? 0) + 1);
    for (const item of aboveBox.items) {
      expect(item.top).toBeGreaterThanOrEqual(0);
      expect(item.bottom).toBeLessThanOrEqual(aboveBox.viewport);
    }

    const tight = await frameOf(page, `iframe[data-frame-case="14-6-open-tight"][width="${width}"]`);
    await tight.locator('[role=listbox]').waitFor();
    const tightBox = await tight.evaluate(() => {
      const rect = (selector: string) => {
        const element = document.querySelector(selector);
        if (element === null) return null;
        const box = element.getBoundingClientRect();
        return { top: box.top, bottom: box.bottom, width: box.width, height: box.height };
      };
      return { trigger: rect('.field-trigger'), popup: rect('.field-menu'), viewport: innerHeight };
    });
    expect(tightBox.popup).not.toBeNull();
    expect(tightBox.trigger).not.toBeNull();
    expect(tightBox.popup?.top ?? 0).toBeGreaterThanOrEqual(0);
    expect(tightBox.popup?.bottom ?? 0).toBeLessThanOrEqual(tightBox.viewport);

    records.push({
      width,
      below: belowBox,
      above: aboveBox,
      tight: {
        ...tightBox,
        menuHeight: tightBox.popup?.height ?? 0,
        belowSpace: (tightBox.viewport ?? 0) - (tightBox.trigger?.bottom ?? 0),
        aboveSpace: tightBox.trigger?.top ?? 0,
      },
    });
  }

  mkdirSync(SHOTS, { recursive: true });
  writeFileSync(join(SHOTS, 'select-collision.json'), `${JSON.stringify(records, null, 2)}\n`);
});

test('test_10a_menu_and_tooltip_stack_in_token_order', async ({ page }) => {
  await galleryReady(page, 'menu');
  const menuFrame = await frameOf(page, 'iframe[data-frame-case="13-6-open"][width="390"]');
  await menuFrame.locator('[role=menu]').waitFor();
  const menuZ = await menuFrame.locator('.menu-positioner').evaluate((element) => getComputedStyle(element).zIndex);

  await galleryReady(page, 'tooltip');
  const tooltipFrame = await frameOf(page, 'iframe[data-frame-case="8-1-default"][width="390"]');
  await tooltipFrame.locator('[role=tooltip]').waitFor();
  const tooltipZ = await tooltipFrame
    .locator('.tooltip-positioner')
    .evaluate((element) => getComputedStyle(element).zIndex);

  expect(menuZ).toBe('40');
  expect(tooltipZ).toBe('20');
  expect(Number(menuZ)).toBeGreaterThan(Number(tooltipZ));

  await galleryReady(page, 'top-bar-status', 3);
  const statusFrame = await frameOf(page, `iframe[data-frame-case="${labelOf('top-bar-status', 'panel-open')}"][width="390"]`);
  await statusFrame.locator('.status-panel').waitFor();
  const statusZ = await statusFrame
    .locator('.status-positioner')
    .evaluate((element) => getComputedStyle(element).zIndex);
  expect(statusZ).toBe('45');
  expect(Number(statusZ)).toBeGreaterThan(Number(menuZ));
});

test('test_10a_batch_three_panel_ends_motion_immediately_when_reduced', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });

  await page.locator('[data-probe="status"] button').first().click();
  const panel = page.getByRole('dialog', { name: '저장하지 못했어요' });
  await expect(panel).toBeVisible();
  const durations = await panel.evaluate((element) => getComputedStyle(element).transitionDuration);
  expect(durations.split(',').every((value) => value.trim() === '0s')).toBe(true);
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
});

test('test_10a_result_card_uses_the_shared_dialog', async ({ page }) => {
  const label = labelOf('result-card', 'default');
  const selector = `iframe[data-frame-case="${label}"][width="390"]`;

  await galleryReady(page, 'result-card', 3);
  const frame = await frameOf(page, selector);
  const dialog = frame.locator('[role=dialog]');
  await expect(dialog).toBeVisible();
  await expect(frame.locator('.dialog__actions button')).toHaveCount(3);
  await frame.getByRole('button', { name: '결과 카드 닫기' }).click();
  await expect(dialog).toHaveCount(0);

  await galleryReady(page, 'result-card', 3);
  const reopened = await frameOf(page, selector);
  await reopened.getByRole('button', { name: '결과 카드 닫기' }).press('Escape');
  await expect(reopened.locator('[role=dialog]')).toHaveCount(0);
});

test('test_10a_batch_three_forced_open_shows_the_same_chevron_direction', async ({ page }) => {
  await galleryReady(page, 'top-bar-item', 3);
  const itemFrame = await frameOf(page, 'iframe[data-frame-group="top-bar-item"][width="390"]');
  const itemArrow = await itemFrame
    .locator(`[data-case="${labelOf('top-bar-item', 'open')}"] .top-bar-item__icon--end`)
    .evaluate((element) => getComputedStyle(element).transform);
  expect(itemArrow).not.toBe('none');

  await galleryReady(page, 'top-bar-status', 3);
  const statusFrame = await frameOf(page, 'iframe[data-frame-group="top-bar-status"][width="390"]');
  const statusArrow = await statusFrame
    .locator(`[data-case="${labelOf('top-bar-status', 'open')}"] .top-bar-status__chevron`)
    .evaluate((element) => getComputedStyle(element).transform);
  expect(statusArrow).not.toBe('none');
});

test('test_10a_batch_three_parts_keep_their_boxes_across_states', async ({ page }) => {
  const sizesOf = async (
    partId: string,
    slugs: readonly string[],
    selector: string,
  ): Promise<[number, number][]> => {
    await galleryReady(page, partId, 3);
    const frame = await frameOf(page, `iframe[data-frame-group="${partId}"][width="390"]`);
    const sizes: [number, number][] = [];
    for (const slug of slugs) {
      const size = await frame
        .locator(`[data-case="${labelOf(partId, slug)}"] ${selector}`)
        .first()
        .evaluate((element) => {
          const box = element.getBoundingClientRect();
          return [box.width, box.height];
        });
      sizes.push([Math.round(size[0] * 10) / 10, Math.round(size[1] * 10) / 10]);
    }
    return sizes;
  };
  const equal = (sizes: [number, number][]) =>
    expect(new Set(sizes.map(([width, height]) => `${width}x${height}`)).size).toBe(1);

  equal(await sizesOf('sidebar-item', ['default', 'hover', 'pressed', 'selected', 'disabled', 'focus-visible'], 'button'));
  equal(await sizesOf('top-bar-item', ['default', 'hover', 'pressed', 'open', 'disabled', 'focus-visible'], 'button'));
  equal(await sizesOf('top-bar-status', ['default', 'hover', 'pressed', 'open', 'disabled', 'focus-visible'], 'button'));

  const format = await sizesOf('card', ['format-default', 'format-pressed', 'format-selected', 'format-disabled', 'format-focus-visible'], '.card--format');
  equal(format);
  expect(format[0][0]).toBe(264);
  const scene = await sizesOf('card', ['scene-default', 'scene-pressed', 'scene-selected', 'scene-disabled', 'scene-focus-visible'], '.card--scene');
  equal(scene);
  expect(scene[0][0]).toBe(120);

  const player = await sizesOf('playback-controls', ['default', 'playing', 'hover', 'pressed', 'disabled', 'focus-visible'], '.player__control');
  equal(player);
  expect(player[0]).toEqual([40, 40]);
});

test('test_10a_batch_three_controls_open_move_and_toggle', async ({ page }) => {
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });

  const menuTrigger = page.locator('[data-probe="top-bar-item"] button').first();
  await menuTrigger.focus();
  await menuTrigger.press('Enter');
  const menu = page.getByRole('menu', { name: '영상 설정' });
  await expect(menu).toBeVisible();
  await expect(menuTrigger).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(menu).toHaveCount(0);
  await expect(menuTrigger).toHaveAttribute('aria-expanded', 'false');
  await expect(menuTrigger).toBeFocused();

  const statusTrigger = page.locator('[data-probe="status"] button').first();
  await statusTrigger.click();
  const panel = page.getByRole('dialog', { name: '저장하지 못했어요' });
  await expect(panel).toBeVisible();
  await expect(statusTrigger).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
  await expect(statusTrigger).toHaveAttribute('aria-expanded', 'false');
  await expect(statusTrigger).toBeFocused();

  await page.locator('[data-probe="stage"]').getByRole('button', { name: '대본' }).click();
  await expect(page.locator('[data-probe="stage"] [aria-current="step"]')).toContainText('대본');
  await expect(page.locator('[data-probe="log"]')).toHaveText('stage:script');

  await page.locator('[data-probe="reorder"]').getByRole('button', { name: '아래로 이동: 첫 장면' }).click();
  await expect(page.locator('[data-probe="log"]')).toHaveText('order:scene-2,scene-1,scene-3');
  await expect(
    page.locator('[data-probe="reorder"] .reorder-row').first().getByRole('button', {
      name: '순서 바꾸기: 둘째 장면',
    }),
  ).toBeVisible();

  await page.locator('[data-probe="card"]').getByRole('button', { name: '세로 영상' }).click();
  await expect(
    page.locator('[data-probe="card"]').getByRole('button', { name: '세로 영상' }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('[data-probe="log"]')).toHaveText('card:format');

  const playback = page.locator('[data-probe="playback"]');
  await playback.getByRole('button', { name: '재생' }).click();
  await expect(playback.getByRole('button', { name: '일시정지' })).toBeVisible();
  const slider = playback.getByRole('slider', { name: '재생 위치' });
  await slider.focus();
  await page.keyboard.press('ArrowRight');
  await expect(slider).toHaveValue('21');
  await expect(page.locator('[data-probe="log"]')).toHaveText('seek:21');
  await playback.getByRole('button', { name: '소리 끄기' }).click();
  await expect(playback.getByRole('button', { name: '소리 켜기' })).toBeVisible();
});

test('test_10a_toast_open_transition_runs', async ({ page }) => {
  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    const state = window as Window & { __toastTransitions?: string[] };
    state.__toastTransitions = [];
    document.addEventListener('transitionstart', (event) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.classList.contains('toast-surface')) {
        state.__toastTransitions?.push(`${event.propertyName}:${target.dataset.state ?? ''}`);
      }
    });
  });

  await page.getByRole('button', { name: '알림 열기' }).click();
  await expect(page.getByRole('status')).toHaveAttribute('data-state', 'open');
  await page.waitForFunction(() => {
    const state = window as Window & { __toastTransitions?: string[] };
    return (state.__toastTransitions ?? []).includes('opacity:open');
  });
});

test('test_10a_gallery_has_no_ref_warnings', async ({ page }) => {
  const messages: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') messages.push(message.text());
  });
  page.on('pageerror', (error) => messages.push(error.message));

  await page.goto(PROBE, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-probe="menu"] button').first().click();
  await expect(page.getByRole('menu')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.locator('[data-probe="select"] [role=combobox]').click();
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.locator('[data-probe="tooltip"] button').first().focus();
  await expect(page.getByRole('tooltip')).toBeVisible();

  await page.locator('[data-probe="top-bar-item"] button').first().click();
  await expect(page.getByRole('menu', { name: '영상 설정' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toHaveCount(0);

  await page.locator('[data-probe="status"] button').first().click();
  await expect(page.getByRole('dialog', { name: '저장하지 못했어요' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);

  expect(messages.filter((message) => message.includes('Function components cannot be given refs'))).toEqual(
    [],
  );
});

test('test_10a_one_part_view_keeps_opened_surfaces_inside_the_shown_box', async ({ page }) => {
  // The default view shows one part and cuts each frame to the area its cases use.
  await page.setViewportSize({ width: 1680, height: 940 });
  await page.goto(`${GALLERY}?batch=1&part=value-field`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await expect(page.locator('iframe')).not.toHaveCount(0);
  const ids = await page
    .locator('[data-part]')
    .evaluateAll((elements) => elements.map((element) => element.getAttribute('data-part')));
  expect(ids).toEqual(['value-field']);

  const inside = async (selector: string, surface: string) => {
    const frameBox = await page.locator(selector).evaluate((element) => {
      const box = element.parentElement?.getBoundingClientRect();
      return box === undefined ? null : { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
    });
    if (frameBox === null) throw new Error(`missing box: ${selector}`);
    const frame = await frameOf(page, selector);
    const tip = await frame.locator(surface).first().boundingBox();
    if (tip === null) throw new Error(`missing surface: ${surface}`);
    expect(tip.x).toBeGreaterThanOrEqual(frameBox.left - 0.5);
    expect(tip.x + tip.width).toBeLessThanOrEqual(frameBox.right + 0.5);
    expect(tip.y).toBeGreaterThanOrEqual(frameBox.top - 0.5);
    expect(tip.y + tip.height).toBeLessThanOrEqual(frameBox.bottom + 0.5);
  };

  // A menu opened by hand inside the 1920 state list, then the reason tooltip of its row.
  const list = 'iframe[data-frame-group="value-field"][width="1920"]';
  const listFrame = await frameOf(page, list);
  await listFrame.locator(`[data-case="${labelOf('value-field', 'default')}"] [role=combobox]`).click();
  const row = listFrame.locator('[aria-label="로봇 목소리 곧 지원"]');
  await row.hover();
  await expect(listFrame.getByRole('tooltip')).toBeVisible();
  await expect.poll(async () => {
    try {
      await inside(list, '[role=tooltip]');
      return true;
    } catch {
      return false;
    }
  }).toBe(true);
  await inside(list, '[role=listbox]');

  // The same tooltip inside a popup case frame.
  const popup = `iframe[data-frame-case="${labelOf('value-field', 'open')}"][width="1920"]`;
  await page.locator(popup).scrollIntoViewIfNeeded();
  const popupFrame = await frameOf(page, popup);
  await popupFrame.locator('[aria-label="로봇 목소리 곧 지원"]').hover();
  await expect(popupFrame.getByRole('tooltip')).toBeVisible();
  await expect.poll(async () => {
    try {
      await inside(popup, '[role=tooltip]');
      return true;
    } catch {
      return false;
    }
  }).toBe(true);
});
