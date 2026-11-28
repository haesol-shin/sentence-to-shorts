import { expect, test, type Page } from '@playwright/test';

import { findPart, inlineCases } from '../../src/gallery/items';

const GALLERY = '/src/gallery/index.html';

/**
 * Every part that draws a half circle. The list is the result of searching the
 * parts for `--radius-pill` and keeping the ones with text or an icon at an end;
 * `components/README.md` states the spacing rule they share.
 */
const PILL_PART_IDS = [
  'button-primary',
  'button-secondary',
  'button-ghost',
  'button-icon',
  'chip-remove',
  'chip',
  'tag',
  'radio',
  'stage-indicator',
  'menu',
  'value-field',
  'text-field',
  'settings-row',
  'send-button',
  'composer',
  'file-chip',
  'sidebar-item',
  'top-bar-item',
  'top-bar-status',
  'reorder-list',
  'playback-controls',
] as const;

/** White-surface parts hover to #F2F4F6; grey-surface parts hover to #DADDE1. */
const HOVER_WHITE = 'rgb(242, 244, 246)';
const HOVER_GREY = 'rgb(218, 221, 225)';

test.describe.configure({ mode: 'serial', timeout: 300_000 });

// eslint-disable-next-line no-empty-pattern
test.beforeEach(({}, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'one chromium measurement');
});

async function openGroup(page: Page, partId: string): Promise<void> {
  const part = findPart(partId);
  if (part === undefined) throw new Error(`missing part: ${partId}`);
  const cases = inlineCases(part);
  await page.setViewportSize({ width: 1920, height: 2400 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`${GALLERY}?group=${encodeURIComponent(partId)}`, {
    waitUntil: 'domcontentloaded',
    timeout: 120_000,
  });
  await page.waitForFunction((count) => document.querySelectorAll('[data-case]').length === count, cases.length, {
    timeout: 120_000,
  });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await page.waitForTimeout(150);
}

type PillRow = { label: string; element: string; start: number; end: number; startKind: string; endKind: string };

/** Runs in the page. For each half circle part, the gap from each outer edge to the first mark inside. */
function measurePills(): PillRow[] {
  const rows: PillRow[] = [];
  for (const caseEl of document.querySelectorAll('[data-case]')) {
    const label = caseEl.getAttribute('data-case') ?? '';
    for (const el of caseEl.querySelectorAll('*')) {
      const style = getComputedStyle(el);
      const box = el.getBoundingClientRect();
      if (box.height < 24 || box.height > 60 || box.width < 24 || style.visibility === 'hidden') continue;
      if (!(parseFloat(style.borderTopLeftRadius) >= box.height / 2 - 0.5)) continue;
      if (el.matches('.file-chip__bar, .file-chip__bar-fill, .video-preview__duration')) continue;

      const marks: { kind: string; left: number; right: number }[] = [];
      if (el instanceof HTMLInputElement) {
        marks.push({ kind: 'text', left: box.left + parseFloat(style.paddingLeft) + 1, right: box.left + 1 });
        marks[0].right = box.right - parseFloat(style.paddingRight) - 1;
      }
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
        const parent = node.parentElement;
        if (parent === null || (node.textContent ?? '').trim() === '') continue;
        const parentStyle = getComputedStyle(parent);
        if (parentStyle.visibility === 'hidden' || parentStyle.opacity === '0') continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        const rects = [...range.getClientRects()];
        if (rects.length === 0) continue;
        marks.push({
          kind: 'text',
          left: Math.min(...rects.map((rect) => rect.left)),
          right: Math.max(...rects.map((rect) => rect.right)),
        });
      }
      for (const svg of el.querySelectorAll('svg')) {
        const svgBox = svg.getBoundingClientRect();
        if (svgBox.width === 0) continue;
        // The play and pause glyphs are centered by their box, and the play
        // glyph moves inside that box for its optical centre, so their pill
        // spacing is judged on the box, not on the shape ink.
        if (svg.classList.contains('play-glyph') || svg.classList.contains('pause-glyph')) {
          marks.push({ kind: 'icon', left: svgBox.left, right: svgBox.right });
          continue;
        }
        const matrix = svg.getScreenCTM();
        const scale = matrix === null ? 1 : Math.hypot(matrix.a, matrix.b);
        let left = Infinity;
        let right = -Infinity;
        // The ink of an icon is its strokes, not its box, so the spacing is judged on the ink.
        for (const shape of svg.querySelectorAll('path, circle, rect, line, polyline, polygon, ellipse')) {
          const shapeBox = shape.getBoundingClientRect();
          const half = ((parseFloat(getComputedStyle(shape).strokeWidth) || 0) * scale) / 2;
          left = Math.min(left, shapeBox.left - half);
          right = Math.max(right, shapeBox.right + half);
        }
        marks.push({ kind: 'icon', left, right });
      }
      for (const solid of el.querySelectorAll('.tag__dot, .spinner')) {
        const solidBox = solid.getBoundingClientRect();
        if (solidBox.width > 0) marks.push({ kind: 'icon', left: solidBox.left, right: solidBox.right });
      }
      // An icon alone is centered by its box (a play triangle is not centered by ink); text alone has two sides.
      if (marks.length === 0 || (marks.length === 1 && marks[0].kind === 'icon')) continue;
      marks.sort((a, b) => a.left - b.left);
      const first = marks[0];
      const last = marks.reduce((best, mark) => (mark.right > best.right ? mark : best), marks[0]);
      rows.push({
        label,
        element: `${el.tagName.toLowerCase()}.${String(el.getAttribute('class') ?? '').split(' ')[0]}`,
        start: Math.round((first.left - box.left) * 10) / 10,
        end: Math.round((box.right - last.right) * 10) / 10,
        startKind: first.kind,
        endKind: last.kind,
      });
    }
  }
  return rows;
}

test('test_w0_pill_parts_have_equal_inner_padding_on_the_icon_side_and_the_text_side', async ({ page }) => {
  const uneven: string[] = [];
  const measuredParts = new Set<string>();
  for (const partId of PILL_PART_IDS) {
    await openGroup(page, partId);
    const rows = await page.evaluate(measurePills);
    for (const row of rows) {
      measuredParts.add(partId);
      if (Math.abs(row.start - row.end) > 1) {
        uneven.push(`${partId} ${row.label} ${row.element}: ${row.startKind} ${row.start} vs ${row.endKind} ${row.end}`);
      }
    }
  }
  // A part that loses its marks must not drop out of the measurement unnoticed.
  expect([...measuredParts].sort()).toEqual(
    [
      'button-primary',
      'button-secondary',
      'button-ghost',
      'chip',
      'tag',
      'radio',
          'stage-indicator',
      'menu',
      'value-field',
      'settings-row',
      'composer',
      'send-button',
      'text-field',
      'top-bar-item',
      'top-bar-status',
      'playback-controls',
    ].sort(),
  );
  expect(uneven).toEqual([]);
});

test('test_w0_pill_parts_with_text_and_an_icon_start_at_half_their_height', async ({ page }) => {
  // The text-side gap equals half the height (the half circle's radius) for the sized pills.
  const expected: { part: string; label: string; element: string; gap: number }[] = [
    { part: 'button-primary', label: '1-1-default', element: 'button.button', gap: 22 },
    { part: 'menu', label: '13-1-default', element: 'button.button', gap: 22 },
    { part: 'value-field', label: '14-1-default', element: 'button.field-trigger', gap: 22 },
  ];
  for (const { part, label, element, gap } of expected) {
    await openGroup(page, part);
    const rows = (await page.evaluate(measurePills)).filter((row) => row.label === label && row.element === element);
    expect(rows.length, `${part} ${label}`).toBeGreaterThan(0);
    for (const row of rows) {
      expect(Math.abs(row.start - gap), `${part} start`).toBeLessThanOrEqual(1);
      expect(Math.abs(row.end - gap), `${part} end`).toBeLessThanOrEqual(1);
    }
  }
});

test('test_w0_notice_icon_and_first_line_share_a_center', async ({ page }) => {
  await openGroup(page, 'notice');
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll('[data-case]')].map((caseEl) => {
      const icon = caseEl.querySelector('.notice__icon svg')?.getBoundingClientRect();
      const title = caseEl.querySelector('.notice__title');
      const range = document.createRange();
      range.selectNodeContents(title ?? caseEl);
      const line = range.getClientRects()[0];
      return {
        label: caseEl.getAttribute('data-case'),
        icon: icon === undefined ? null : icon.top + icon.height / 2,
        text: line === undefined ? null : line.top + line.height / 2,
      };
    }),
  );
  expect(rows.length).toBe(4);
  for (const row of rows) {
    expect(row.icon, `${row.label} icon`).not.toBeNull();
    expect(row.text, `${row.label} text`).not.toBeNull();
    expect(Math.abs((row.icon ?? 0) - (row.text ?? 0)), row.label ?? '').toBeLessThanOrEqual(1);
  }
});

test('test_w0_hover_background_is_the_decided_grey_of_its_surface', async ({ page }) => {
  const colorOf = (page: Page, selector: string) =>
    page.locator(selector).first().evaluate((element) => getComputedStyle(element).backgroundColor);
  const hoverOver = async (selector: string) => {
    const target = page.locator(selector).first();
    await target.scrollIntoViewIfNeeded();
    await target.hover();
    await page.waitForTimeout(60);
    return colorOf(page, selector);
  };

  // White surface parts hover to the white surface hover.
  await openGroup(page, 'button-icon');
  expect(await hoverOver('[data-case="4-1-default"] .icon-button')).toBe(HOVER_WHITE);
  await openGroup(page, 'radio');
  expect(await hoverOver('[data-case="11-1-default"] .radio-option')).toBe(HOVER_WHITE);
  await openGroup(page, 'chip-remove');
  expect(await hoverOver('[data-case="5-1-default"] .close-button--md')).toBe(HOVER_WHITE);

  // Grey surface parts hover to the grey surface hover.
  await openGroup(page, 'menu');
  expect(await hoverOver('[data-case="13-1-default"] .button')).toBe(HOVER_GREY);
  await openGroup(page, 'value-field');
  expect(await hoverOver('[data-case="14-1-default"] .field-trigger')).toBe(HOVER_GREY);
  await openGroup(page, 'top-bar-item');
  expect(await hoverOver('[data-case="32-1-default"] .top-bar-item')).toBe(HOVER_GREY);
  await openGroup(page, 'sidebar-item');
  expect(await hoverOver('[data-case="31-1-default"] .sidebar-item')).toBe(HOVER_GREY);

  // One hover value per surface: the row, its grip and its move buttons are the same white surface.
  await openGroup(page, 'reorder-list');
  const row = '[data-case="36-2-hover"] .reorder-row:nth-child(2)';
  await page.mouse.move(0, 0);
  expect(await hoverOver(`${row} .reorder-row__move`)).toBe(HOVER_WHITE);
  expect(await hoverOver(`${row} .reorder-row__grip`)).toBe(HOVER_WHITE);
});

test('test_w0_top_bar_status_working_spinner_keeps_the_text_side_gap', async ({ page }) => {
  // The working tone puts a spinner where the tone mark goes. It is a portal case, so the
  // group view never measures it.
  await page.setViewportSize({ width: 1920, height: 2400 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`${GALLERY}?case=${encodeURIComponent('33-8-working-open')}`, {
    waitUntil: 'domcontentloaded',
    timeout: 120_000,
  });
  await page.waitForSelector('[data-case="33-8-working-open"] .top-bar-status__trigger');
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  const rows = (await page.evaluate(measurePills)).filter((row) => row.element.includes('top-bar-status'));
  expect(rows.length).toBe(1);
  expect(rows[0].startKind).toBe('icon');
  expect(Math.abs(rows[0].start - rows[0].end)).toBeLessThanOrEqual(1);
});

test('test_w0_file_chip_receiving_shows_progress_and_failure_retry_is_an_icon', async ({ page }) => {
  await openGroup(page, 'file-chip');
  const bar = page.locator('[data-case="19-2-loading"] [role="progressbar"]');
  await expect(bar).toHaveCount(1);
  const widths = await bar.evaluate((element) => {
    const track = element.getBoundingClientRect();
    const fill = element.querySelector('.file-chip__bar-fill')?.getBoundingClientRect();
    return { track: track.width, fill: fill?.width ?? 0, height: track.height };
  });
  expect(widths.height).toBeGreaterThan(0);
  expect(widths.fill / widths.track).toBeGreaterThan(0.4);
  expect(widths.fill / widths.track).toBeLessThan(0.5);
  await expect(page.locator('[data-case="19-1-default"] [role="progressbar"]')).toHaveCount(0);

  for (const label of ['19-3-error', '19-5-error-retry']) {
    const chip = page.locator(`[data-case="${label}"] .file-chip`);
    await expect(chip).not.toContainText('다시');
    const retry = chip.getByRole('button', { name: '재시도' });
    await expect(retry).toHaveCount(1);
    await expect(retry.locator('svg')).toHaveCount(1);
    expect(((await retry.textContent()) ?? '').trim()).toBe('');
  }
});

test('test_w0_confirm_range_arrow_is_midway_between_the_two_values', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto(`${GALLERY}?case=${encodeURIComponent('24-1-default')}`, {
    waitUntil: 'domcontentloaded',
    timeout: 120_000,
  });
  await page.waitForSelector('.range-dialog__values');
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll('.range-dialog__values')].map((values) => {
      const edge = (selector: string, side: 'left' | 'right') => {
        const range = document.createRange();
        range.selectNodeContents(values.querySelector(selector) as Element);
        const rect = range.getBoundingClientRect();
        return rect[side];
      };
      const arrow = (values.querySelector('.range-dialog__arrow') as Element).getBoundingClientRect();
      const before = edge('.range-dialog__before', 'right');
      const after = edge('.range-dialog__after', 'left');
      return { gapBefore: arrow.left - before, gapAfter: after - arrow.right };
    }),
  );
  expect(rows.length).toBe(2);
  for (const row of rows) expect(Math.abs(row.gapBefore - row.gapAfter)).toBeLessThanOrEqual(1);
  await expect(page.locator('.range-dialog__scope-list li')).toHaveCount(2);
  await expect(page.locator('.range-dialog__scope-list')).not.toContainText('그대로 둠');
});

test('test_w0_compact_icon_button_draws_32_and_keeps_the_44_hit_area', async ({ page }) => {
  await openGroup(page, 'button-icon');
  const normal = await page.locator('[data-case="4-1-default"] .icon-button').boundingBox();
  const compact = page.locator('[data-case="4-7-compact"] .icon-button');
  const box = await compact.boundingBox();
  expect(normal?.width).toBe(44);
  expect(box?.width).toBe(32);
  expect(box?.height).toBe(32);
  const hit = await compact.evaluate((element) => {
    const after = getComputedStyle(element, '::after');
    return { width: parseFloat(after.width), height: parseFloat(after.height) };
  });
  expect(hit).toEqual({ width: 44, height: 44 });
});
