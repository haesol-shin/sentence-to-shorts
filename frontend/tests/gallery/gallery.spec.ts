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

async function galleryReady(page: Page, partId?: string): Promise<void> {
  const query = partId === undefined ? '?batch=1' : `?batch=1&part=${encodeURIComponent(partId)}`;
  await page.goto(`${GALLERY}${query}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.waitForFunction(
    (expected) => document.querySelectorAll('[data-part]').length === expected,
    partId === undefined ? 16 : 1,
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

test('test_10a_gallery_lists_every_part_and_numbered_case_in_order', async ({ page }) => {
  await galleryReady(page);

  const ids = await page
    .locator('[data-part]')
    .evaluateAll((elements) => elements.map((element) => element.getAttribute('data-part')));
  expect(ids).toEqual(galleryParts.map((part) => part.id));

  for (const part of galleryParts) {
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
      await expect(frame.locator('[role=menu], [role=listbox], [role=tooltip]').first()).toBeVisible({
        timeout: 10_000,
      });
    }
  }
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

  expect(messages.filter((message) => message.includes('Function components cannot be given refs'))).toEqual(
    [],
  );
});
