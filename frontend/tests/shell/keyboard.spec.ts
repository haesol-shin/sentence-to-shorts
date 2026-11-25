import { expect, test, type Page } from '@playwright/test';

import { capture } from '../support/capture';

declare global {
  interface Window {
    /** Installed by the init script below, so a test can open a soft keyboard. */
    openSoftKeyboard?: (height: number) => void;
  }
}

const KEYBOARD_INSET = 364;

/**
 * Playwright cannot open a real software keyboard, so the test installs a
 * visual viewport it can shrink and fires the events a phone fires.
 */
async function installSoftKeyboard(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const handlers = new Set<() => void>();
    const state = { open: false, height: 0 };
    const viewport = {
      // While closed the fake mirrors the layout viewport, as a phone does
      // before a keyboard opens; only an opened keyboard shrinks it.
      get height() {
        return state.open ? state.height : window.innerHeight;
      },
      width: window.innerWidth,
      offsetTop: 0,
      offsetLeft: 0,
      scale: 1,
      pageTop: 0,
      pageLeft: 0,
      addEventListener: (type: string, handler: () => void) => {
        if (type === 'resize' || type === 'scroll') {
          handlers.add(handler);
        }
      },
      removeEventListener: (type: string, handler: () => void) => {
        if (type === 'resize' || type === 'scroll') {
          handlers.delete(handler);
        }
      },
      dispatchEvent: () => true,
    };
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
    Object.defineProperty(window, 'openSoftKeyboard', {
      configurable: true,
      value: (height: number) => {
        state.open = true;
        state.height = height;
        for (const handler of handlers) {
          handler();
        }
      },
    });
  });
}

/** Covers the bottom `inset` pixels of the layout viewport, as a keyboard does. */
async function openKeyboard(page: Page, inset: number): Promise<number> {
  return page.evaluate((value) => {
    const keyboardTop = window.innerHeight - value;
    window.openSoftKeyboard?.(keyboardTop);
    return keyboardTop;
  }, inset);
}

const overlaps = (
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number },
): boolean =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

test('test_23_the_first_screen_input_stays_above_the_keyboard', async ({ page }) => {
  await installSoftKeyboard(page);
  await page.goto('/');

  const composer = page.locator('[data-slot="first-screen"] [data-slot="composer"]');
  await composer.getByRole('textbox').focus();
  const keyboardTop = await openKeyboard(page, KEYBOARD_INSET);

  const box = await composer.boundingBox();
  expect(box).not.toBeNull();
  if (box === null) return;
  expect(box.y + box.height).toBeLessThanOrEqual(keyboardTop);
});

test('test_23_the_stage_input_sits_above_the_keyboard_without_overlap', async ({ page }) => {
  await installSoftKeyboard(page);
  await page.goto('/');

  const width = page.viewportSize()?.width ?? 0;
  test.skip(width >= 768, 'the docked composer belongs to the phone layout');

  await page.getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' }).fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();

  await page.getByRole('button', { name: '단계 열기' }).click();
  await page.getByRole('menuitem', { name: '편집' }).click();
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();

  const keyboardTop = await openKeyboard(page, KEYBOARD_INSET);

  await expect(page.locator('[data-slot="preview"]')).toHaveAttribute('data-collapsed', 'true');

  const dock = page.locator('[data-slot="composer-dock"] [data-slot="composer"]');
  const dockBox = await dock.boundingBox();
  expect(dockBox).not.toBeNull();
  if (dockBox === null) return;

  expect(dockBox.y + dockBox.height).toBeLessThanOrEqual(keyboardTop);

  const preview = await page.locator('[data-slot="preview"]').boundingBox();
  expect(preview).not.toBeNull();
  if (preview === null) return;
  expect(overlaps(dockBox, preview)).toBe(false);
});

test('test_23_captures_the_job_status_in_the_top_bar_while_typing', async ({ page }, testInfo) => {
  await installSoftKeyboard(page);
  await page.goto('/');

  const width = page.viewportSize()?.width ?? 0;

  await page.getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' }).fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();
  // The conversation says the wait; a phone keeps the banner, since its rail is hidden.
  if (width >= 768) {
    await expect(page.locator('[data-slot="job-banner"]')).toBeHidden();
    await expect(page.locator('[data-slot="top-bar"] [data-slot="job-status"]')).toHaveCount(0);
    await capture(page, testInfo, `tests/screens/keyboard-status-${width}.png`);
    return;
  }
  await expect(page.locator('[data-slot="job-banner"]')).toBeVisible();

  const barBefore = await page.locator('[data-slot="top-bar"]').boundingBox();

  await openKeyboard(page, KEYBOARD_INSET);

  const status = page.locator('[data-slot="top-bar"] [data-slot="job-status"]');
  await expect(status).toBeVisible();
  const barAfter = await page.locator('[data-slot="top-bar"]').boundingBox();
  expect(barAfter?.height).toBe(barBefore?.height);
  await capture(page, testInfo, `tests/screens/keyboard-status-${width}.png`);
});
