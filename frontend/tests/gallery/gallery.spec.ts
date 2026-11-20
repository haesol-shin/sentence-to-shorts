import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type Frame, type Locator, type Page } from '@playwright/test';

import { HIT_AREA_PART_IDS, galleryParts, inlineCases, portalCases } from '../../src/gallery/items';
import type { HitAreaRow } from './measure';

type GalleryWheelEvent = {
  ctrl: boolean;
  shift: boolean;
  deltaX: number;
  deltaY: number;
  prevented: boolean;
};

declare global {
  interface Window {
    __galleryWheelLog?: GalleryWheelEvent[];
  }
}

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

type ScrollPaneCases = {
  viewport: Locator;
  jump: Locator;
  body: Locator;
};

async function openScrollPane(page: Page): Promise<ScrollPaneCases> {
  await page.goto(`${GALLERY}?group=scroll-pane`, {
    waitUntil: 'domcontentloaded',
    timeout: 120_000,
  });
  await page.waitForFunction(() => document.querySelectorAll('[data-case]').length === 3, undefined, {
    timeout: 120_000,
  });
  await page.evaluate(async () => {
    await document.fonts.ready;
    window.scrollTo(0, 0);
  });
  const longCase = page.locator(`[data-case="${labelOf('scroll-pane', 'long')}"]`);
  return {
    viewport: longCase.locator('.scroll-pane__viewport'),
    jump: longCase.getByRole('button', { name: '아래로 넘기기' }),
    body: longCase.locator('.demo-scroll-pane__line').first(),
  };
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
        const shown = await frame
          .locator('[data-case]')
          .evaluateAll((elements) =>
            elements.map((element) => ({
              label: element.getAttribute('data-case') ?? '',
              order: Number(getComputedStyle(element).order),
            })),
          );
        expect(shown.map((entry) => entry.label).sort()).toEqual(
          inlineCases(part)
            .map((entry) => entry.label)
            .sort(),
        );
        // The DOM order is the shown order, so keyboard order follows what is on screen.
        const orders = shown.map((entry) => entry.order);
        expect(orders).toEqual([...orders].sort((x, y) => x - y));
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
      ['1-1-default', '1-2-hover', '1-3-pressed', '1-4-disabled', '1-6-focus-visible'],
      'button',
    ),
  );
  // The stop control keeps the height and hit area; the label decides the width.
  const runningButton = await sizesOf('button-primary', ['1-5-loading'], 'button');
  const startButton = await sizesOf('button-primary', ['1-1-default'], 'button');
  expect(runningButton[0][1]).toBe(44);
  expect(runningButton[0][0]).toBeGreaterThan(startButton[0][0]);
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
  const switchBoxes = await sizesOf(
    'switch',
    [
      '12-1-default',
      '12-2-hover',
      '12-3-pressed',
      '12-5-disabled',
      '12-6-focus-visible',
      '12-4-selected',
      '12-7-label-element',
    ],
    '.switch-option',
  );
  equal(switchBoxes);
  expect(switchBoxes[0][1]).toBe(44);
});

test('test_10a_decided_part_sizes_and_hit_areas', async ({ page }) => {
  await galleryReady(page, 'card', 3);
  const cardFrame = await frameOf(page, 'iframe[data-frame-group="card"][width="390"]');
  const format = labelOf('card', 'format-default');
  const cardBox = await cardFrame.locator(`[data-case="${format}"] .card--format`).boundingBox();
  const mediaBox = await cardFrame.locator(`[data-case="${format}"] .card__media`).boundingBox();
  if (cardBox === null || mediaBox === null) throw new Error('missing format card');
  expect([cardBox.width, mediaBox.width, mediaBox.height]).toEqual([216, 200, 150]);

  await galleryReady(page, 'tag');
  const tagFrame = await frameOf(page, 'iframe[data-frame-group="tag"][width="390"]');
  const neutral = labelOf('tag', 'neutral');
  const tag = tagFrame.locator(`[data-case="${neutral}"] .tag`).first();
  const tagBox = await tag.boundingBox();
  if (tagBox === null) throw new Error('missing tag');
  expect(tagBox.height).toBe(26);
  const tagLook = await tag.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const above = document.elementFromPoint(x, box.top - 8);
    const below = document.elementFromPoint(x, box.bottom + 8);
    return {
      radius: getComputedStyle(element).borderRadius,
      above: above === element || element.contains(above),
      below: below === element || element.contains(below),
    };
  });
  expect(tagLook.radius).toBe('13px');
  expect(tagLook.above).toBe(true);
  expect(tagLook.below).toBe(true);

  const tagColors = await tagFrame.evaluate((label) => {
    const probe = document.createElement('span');
    document.body.append(probe);
    probe.style.backgroundColor = 'var(--muted)';
    const muted = getComputedStyle(probe).backgroundColor;
    probe.style.cssText = '';
    probe.style.color = 'var(--foreground)';
    const foreground = getComputedStyle(probe).color;
    probe.remove();
    const element = document.querySelector(`[data-case="${label}"] .tag`);
    const style = element === null ? null : getComputedStyle(element);
    return {
      muted,
      foreground,
      background: style?.backgroundColor ?? '',
      color: style?.color ?? '',
    };
  }, neutral);
  expect(tagColors.background).toBe(tagColors.muted);
  expect(tagColors.color).toBe(tagColors.foreground);

  await galleryReady(page, 'switch');
  const switchFrame = await frameOf(page, 'iframe[data-frame-group="switch"][width="390"]');
  const offLabel = labelOf('switch', 'default');
  const onLabel = labelOf('switch', 'selected');
  const off = switchFrame.locator(`[data-case="${offLabel}"]`);
  const track = await off.locator('.switch-option__track').boundingBox();
  const thumb = await off.locator('.switch-option__thumb').boundingBox();
  const row = await off.locator('.switch-option').boundingBox();
  if (track === null || thumb === null || row === null) throw new Error('missing switch');
  expect([track.width, track.height]).toEqual([44, 26]);
  expect([thumb.width, thumb.height]).toEqual([20, 20]);
  expect(row.height).toBe(44);

  const onThumb = await switchFrame
    .locator(`[data-case="${onLabel}"] .switch-option__thumb`)
    .evaluate((element) => getComputedStyle(element).transform);
  expect(onThumb).not.toBe('none');

  const switchColors = await switchFrame.evaluate(
    ({ off: offCase, on: onCase }) => {
      const probe = document.createElement('span');
      document.body.append(probe);
      const resolve = (property: 'color' | 'backgroundColor' | 'borderTopColor', name: string) => {
        probe.style.cssText = '';
        if (property === 'color') probe.style.color = `var(${name})`;
        if (property === 'backgroundColor') probe.style.backgroundColor = `var(${name})`;
        if (property === 'borderTopColor') probe.style.borderColor = `var(${name})`;
        return getComputedStyle(probe)[property];
      };
      const tokens = {
        card: resolve('backgroundColor', '--card'),
        border: resolve('borderTopColor', '--border'),
        foreground: resolve('backgroundColor', '--foreground'),
        selected: resolve('backgroundColor', '--state-selected'),
      };
      probe.remove();
      const read = (label: string, part: string) => {
        const element = document.querySelector(`[data-case="${label}"] ${part}`);
        return element === null ? null : getComputedStyle(element);
      };
      const offTrack = read(offCase, '.switch-option__track');
      const offThumb = read(offCase, '.switch-option__thumb');
      const onTrack = read(onCase, '.switch-option__track');
      return {
        tokens,
        offBackground: offTrack?.backgroundColor ?? '',
        offBorder: offTrack?.borderTopColor ?? '',
        offThumb: offThumb?.backgroundColor ?? '',
        onBackground: onTrack?.backgroundColor ?? '',
        onBorder: onTrack?.borderTopColor ?? '',
      };
    },
    { off: offLabel, on: onLabel },
  );
  expect(switchColors.offBackground).toBe(switchColors.tokens.card);
  expect(switchColors.offBorder).toBe(switchColors.tokens.border);
  expect(switchColors.offThumb).toBe(switchColors.tokens.foreground);
  expect(switchColors.onBackground).toBe(switchColors.tokens.selected);
  expect(switchColors.onBorder).toBe(switchColors.tokens.selected);
});

test('test_10a_radio_takes_the_check_space_only_when_selected', async ({ page }) => {
  type OptionSize = { width: number; height: number; checkVisible: boolean };
  const sizesOf = async (
    partId: string,
    labels: readonly string[],
    selector: string,
  ): Promise<OptionSize[]> => {
    await galleryReady(page, partId);
    const frame = await frameOf(page, `iframe[data-frame-group="${partId}"][width="390"]`);
    const sizes: OptionSize[] = [];
    for (const label of labels) {
      const option = frame.locator(`[data-case="${label}"] ${selector}`).first();
      const box = await option.boundingBox();
      if (box === null) throw new Error(`missing option: ${label}`);
      const checkVisible = await option.locator('svg').first().isVisible();
      sizes.push({
        width: Math.round(box.width * 10) / 10,
        height: Math.round(box.height * 10) / 10,
        checkVisible,
      });
    }
    return sizes;
  };

  const radioOff = await sizesOf('radio', ['11-1-default'], '.radio-option');
  const radioOn = await sizesOf('radio', ['11-4-selected'], '.radio-option');
  expect(radioOff[0].checkVisible).toBe(false);
  expect(radioOn[0].checkVisible).toBe(true);
  expect(radioOn[0].width).toBeGreaterThan(radioOff[0].width);
  expect(radioOn[0].height).toBe(44);
  expect(radioOff[0].height).toBe(44);

  const switchOff = await sizesOf('switch', ['12-1-default'], '.switch-option');
  const switchOn = await sizesOf('switch', ['12-4-selected'], '.switch-option');
  expect(switchOff[0].checkVisible).toBe(false);
  expect(switchOn[0].checkVisible).toBe(false);
  expect(switchOn[0].width).toBe(switchOff[0].width);
  expect(switchOn[0].height).toBe(44);
  expect(switchOff[0].height).toBe(44);

  const rowOff = await sizesOf('settings-row', ['16-1-default'], '.switch-option');
  const rowOn = await sizesOf('settings-row', ['16-2-on'], '.switch-option');
  expect(rowOff[0].checkVisible).toBe(false);
  expect(rowOn[0].checkVisible).toBe(false);
  expect(rowOn[0].width).toBe(rowOff[0].width);
  expect(rowOn[0].height).toBe(44);
  expect(rowOff[0].height).toBe(44);
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

type Role = Parameters<Locator['getByRole']>[0];

/** Browser role names differ from the DOM tag for a few controls. */
const ARIA_ROLES: Record<string, Role> = {
  a: 'link',
  input: 'textbox',
  select: 'combobox',
  textarea: 'textbox',
};
const ROVING_ROLES: Record<string, true> = {
  radio: true,
  tab: true,
  menuitem: true,
  option: true,
};
const TABBABLE =
  'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href], [role=switch]:not([aria-disabled=true]), [role=radio]:not([aria-disabled=true]), [role=tab]:not([aria-disabled=true]), [role=menuitem]:not([aria-disabled=true]), [role=option]:not([aria-disabled=true]), [role=combobox]:not([aria-disabled=true])';

const HIT_AREA_RECORD = JSON.parse(
  readFileSync(join(process.cwd(), 'tests', 'gallery', 'hit-area.json'), 'utf8'),
) as { parts: Record<string, Record<string, HitAreaRow[]>> };

/** The name the browser exposes for a control, not a name the test guessed. */
async function exposedName(locator: Locator): Promise<string> {
  const snapshot = (await locator.ariaSnapshot()).trim().split('\n')[0];
  const match = snapshot.match(/^- [\w-]+ "(.*)"(?: \[[^\]]*\])?:?$/);
  if (match === null) throw new Error(`cannot read the accessible name from ${snapshot}`);
  return match[1];
}

test('test_10a_batch_two_controls_keep_the_decided_visible_sizes', async ({ page }) => {
  await galleryReady(page, 'composer', 2);
  const composer = await frameOf(page, 'iframe[data-frame-group="composer"][width="1920"]');
  const send = await composer
    .locator('[data-case="18-1-default"] button[aria-label="보내기"]')
    .evaluate((element) => Math.round(element.getBoundingClientRect().height));
  expect(send).toBe(32);
  const attach = await composer
    .locator('[data-case="18-1-default"] button[aria-label="파일 넣기"]')
    .evaluate((element) => Math.round(element.getBoundingClientRect().height));
  expect(attach).toBe(44);
  const chips = await composer
    .locator('[data-case="18-6-chips"] .composer-chip')
    .evaluateAll((elements) => elements.map((element) => Math.round(element.getBoundingClientRect().height)));
  expect(chips).toEqual([36, 36]);

  await galleryReady(page, 'file-chip', 2);
  const fileChip = await frameOf(page, 'iframe[data-frame-group="file-chip"][width="1920"]');
  const remove = await fileChip
    .locator('[data-case="19-1-default"] button[aria-label="파일 지우기"]')
    .evaluate((element) => Math.round(element.getBoundingClientRect().height));
  expect(remove).toBe(32);

  await galleryReady(page, 'dialog', 2);
  const dialog = await frameOf(page, 'iframe[data-frame-case="21-1-default"][width="1920"]');
  const dialogButtons = await dialog
    .locator('.dialog button')
    .evaluateAll((elements) => elements.map((element) => Math.round(element.getBoundingClientRect().height)));
  expect(dialogButtons).toEqual([44, 44]);

  await galleryReady(page, 'bottom-sheet', 2);
  const sheet = await frameOf(page, 'iframe[data-frame-case="26-1-default"][width="1920"]');
  const sheetClose = await sheet
    .locator('button[aria-label="닫기"]')
    .evaluate((element) => Math.round(element.getBoundingClientRect().height));
  expect(sheetClose).toBe(44);
});

test('test_10a_batch_two_controls_keep_the_focus_order_and_names', async ({ page }) => {
  test.setTimeout(480_000);
  await page.setViewportSize({ width: 1280, height: 1080 });

  const checkCase = async (scope: Locator, label: string, partId: string) => {
    const rows = (HIT_AREA_RECORD.parts[partId]?.['1280'] ?? []).filter((row) => row.case === label);
    const controls: { row: HitAreaRow; target: Locator; tabIndex: number }[] = [];
    for (const row of rows) {
      const role = ARIA_ROLES[row.role] ?? (row.role as Role);
      const target = scope.getByRole(role, { name: row.name, exact: true });
      await expect(target, `${label} ${row.name} is not one named control`).toHaveCount(1);
      const box = await target.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return [Math.floor(rect.width), Math.floor(rect.height)];
      });
      expect(box, `${label} ${row.name} visible box`).toEqual(row.visible);
      expect(await exposedName(target), `${label} ${row.name} accessible name`).toBe(row.name);
      const tabIndex = await target.evaluate((element) => (element as HTMLElement).tabIndex);
      controls.push({ row, target, tabIndex });
      if (row.disabled) continue;
      if (row.role === 'radio') {
        const grouped = await target.evaluate((element) => element.closest('[role="radiogroup"]') !== null);
        if (!grouped) {
          expect(tabIndex, `${label} ${row.name} is outside a radio group and not tabbable`).toBeGreaterThanOrEqual(0);
        }
      } else if (ROVING_ROLES[row.role] !== true) {
        expect(tabIndex, `${label} ${row.name} is not tabbable`).toBeGreaterThanOrEqual(0);
      }
    }

    const tabbable = controls.filter((control) => !control.row.disabled && control.tabIndex >= 0);
    if (tabbable.length > 0) {
      const first = tabbable[0].target;
      const firstFocused = await first.evaluate((element) => element === document.activeElement);
      if (!firstFocused) {
        const modal = (await scope.locator('[role="dialog"], [role="alertdialog"]').count()) > 0;
        if (modal) {
          // A modal traps focus, so the last tab stop wraps back to the first.
          await tabbable[tabbable.length - 1].target.focus();
        } else {
          // Enter from the element before the case, not by focusing the target itself.
          await first.evaluate((element, selector) => {
            const all = [...document.querySelectorAll(selector)].filter((candidate) => {
              const html = candidate as HTMLElement;
              return (
                html.tabIndex >= 0 &&
                candidate.getClientRects().length > 0 &&
                getComputedStyle(candidate).visibility !== 'hidden'
              );
            });
            const index = all.indexOf(element);
            if (index > 0) {
              (all[index - 1] as HTMLElement).focus();
            } else {
              (document.activeElement as HTMLElement | null)?.blur();
            }
          }, TABBABLE);
        }
        await page.keyboard.press('Tab');
      }
      await expect(first, `${label} first tab entry`).toBeFocused();
      for (let index = 0; index < tabbable.length; index += 1) {
        if (index > 0) await page.keyboard.press('Tab');
        await expect(tabbable[index].target, `${label} ${tabbable[index].row.name} tab focus`).toBeFocused();
      }
    }

    const groupCount = await scope.locator('[role="radiogroup"]').count();
    for (let groupIndex = 0; groupIndex < groupCount; groupIndex += 1) {
      const group = scope.locator('[role="radiogroup"]').nth(groupIndex);
      const radios = group.getByRole('radio');
      const count = await radios.count();
      const names: string[] = [];
      let selected = -1;
      for (let index = 0; index < count; index += 1) {
        names.push(await exposedName(radios.nth(index)));
        const tabIndex = await radios.nth(index).evaluate((element) => (element as HTMLElement).tabIndex);
        if (tabIndex >= 0 && selected === -1) selected = index;
      }
      expect(selected, `${label} radio group has no tab stop`).toBeGreaterThanOrEqual(0);
      await radios.nth(selected).focus();
      for (let index = selected; index > 0; index -= 1) {
        await page.keyboard.press('ArrowUp');
        await expect(radios.nth(index - 1), `${label} radio ArrowUp ${names[index - 1]}`).toBeFocused();
      }
      for (let index = 1; index < count; index += 1) {
        await page.keyboard.press('ArrowDown');
        await expect(radios.nth(index), `${label} radio ArrowDown ${names[index]}`).toBeFocused();
      }
    }
  };

  for (const partId of HIT_AREA_PART_IDS) {
    const part = galleryParts.find((candidate) => candidate.id === partId);
    if (part === undefined) throw new Error(`missing part: ${partId}`);
    if (inlineCases(part).length > 0) {
      await page.goto(`${GALLERY}?group=${encodeURIComponent(part.id)}`, {
        waitUntil: 'domcontentloaded',
        timeout: 120_000,
      });
      await page.waitForFunction(
        (count) => document.querySelectorAll('[data-case]').length === count,
        inlineCases(part).length,
        { timeout: 120_000 },
      );
      await page.evaluate(async () => {
        await document.fonts.ready;
      });
      for (const entry of inlineCases(part)) {
        await checkCase(page.locator(`[data-case="${entry.label}"]`), entry.label, part.id);
      }
    }
    for (const entry of portalCases(part)) {
      await page.goto(`${GALLERY}?case=${encodeURIComponent(entry.label)}`, {
        waitUntil: 'domcontentloaded',
        timeout: 120_000,
      });
      await page.waitForFunction(() => document.querySelectorAll('[data-case]').length === 1, undefined, {
        timeout: 120_000,
      });
      await page.evaluate(async () => {
        await document.fonts.ready;
      });
      await page.waitForTimeout(250);
      await checkCase(page.locator('body'), entry.label, part.id);
    }
  }
});

test('test_10a_toast_opener_tab_reaches_the_undo_action', async ({ page }) => {
  for (const width of [1280, 1920] as const) {
    await page.setViewportSize({ width, height: 1080 });
    await page.goto(`${GALLERY}?probe=1`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('button', { name: '알림 열기' }).click();
    const undo = page.getByRole('button', { name: '되돌리기' });
    await expect(undo).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(undo, `${width} toast opener Tab`).toBeFocused();
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

test('test_10a_running_buttons_become_their_stop_controls', async ({ page }) => {
  await galleryReady(page, 'button-primary');
  const frame = await frameOf(page, 'iframe[data-frame-group="button-primary"][width="390"]');
  const button = frame.locator('[data-case="1-5-loading"] button');
  await expect(button).toHaveAccessibleName('만들기 멈추기');
  await expect(button).toBeEnabled();
  await expect(button).toContainText('■');
  await expect(button.locator('.spinner')).toHaveCount(0);

  await galleryReady(page, 'send-button', 2);
  const sendFrame = await frameOf(page, 'iframe[data-frame-group="send-button"][width="390"]');
  const send = sendFrame.locator('[data-case="17-5-loading"] button');
  await expect(send).toHaveAccessibleName('멈추기');
  await expect(send).toBeEnabled();
  await expect(send).toContainText('■');
  await expect(send.locator('.spinner')).toHaveCount(0);
});

test('test_10a_batch_four_progress_text_and_bar_use_the_foreground_token', async ({ page }) => {
  await galleryReady(page, 'progress', 2);
  const frame = await frameOf(page, 'iframe[data-frame-group="progress"][width="390"]');
  const label = labelOf('progress', 'count');
  await expect(frame.locator(`[data-case="${label}"]`)).toContainText('3 / 5');

  const colors = await frame.evaluate((caseLabel) => {
    const probe = document.createElement('span');
    document.body.append(probe);
    const resolve = (name: string) => {
      probe.style.color = `var(${name})`;
      return getComputedStyle(probe).color;
    };
    const foreground = resolve('--foreground');
    const muted = resolve('--muted');
    probe.remove();
    const box = document.querySelector(`[data-case="${caseLabel}"]`);
    const labelElement = box?.querySelector('.progress__label') ?? null;
    const valueElement = box?.querySelector('.progress__value') ?? null;
    const indicator = box?.querySelector('.progress__indicator') ?? null;
    const track = box?.querySelector('.progress__track') ?? null;
    return {
      foreground,
      muted,
      label: labelElement === null ? '' : getComputedStyle(labelElement).color,
      value: valueElement === null ? '' : getComputedStyle(valueElement).color,
      indicator: indicator === null ? '' : getComputedStyle(indicator).backgroundColor,
      track: track === null ? '' : getComputedStyle(track).backgroundColor,
    };
  }, label);

  expect(colors.label).toBe(colors.foreground);
  expect(colors.value).toBe(colors.foreground);
  expect(colors.indicator).toBe(colors.foreground);
  expect(colors.track).toBe(colors.muted);
});

test('test_10a_batch_four_top_bar_working_tone_keeps_only_its_text_and_spinner_blue', async ({ page }) => {
  await galleryReady(page, 'top-bar-status', 3);
  const label = labelOf('top-bar-status', 'working-open');
  const frame = await frameOf(page, `iframe[data-frame-case="${label}"][width="390"]`);
  const trigger = frame.locator(`[data-case="${label}"] .top-bar-status__trigger`);
  await expect(trigger).toContainText('영상 만드는 중 3 / 5');
  await expect(trigger.locator('.spinner')).toHaveCount(1);

  const colors = await frame.evaluate((caseLabel) => {
    const probe = document.createElement('span');
    document.body.append(probe);
    const resolve = (name: string) => {
      probe.style.color = `var(${name})`;
      return getComputedStyle(probe).color;
    };
    const progress = resolve('--progress');
    const foreground = resolve('--foreground');
    const sub = resolve('--sub');
    probe.remove();
    const box = document.querySelector(`[data-case="${caseLabel}"]`);
    const labelElement = box?.querySelector('.top-bar-status__label') ?? null;
    const iconElement = box?.querySelector('.top-bar-status__icon') ?? null;
    const chevronElement = box?.querySelector('.top-bar-status__chevron') ?? null;
    const panelLabel = document.querySelector('.status-panel .progress__label') ?? null;
    const panelValue = document.querySelector('.status-panel .progress__value') ?? null;
    return {
      progress,
      foreground,
      sub,
      label: labelElement === null ? '' : getComputedStyle(labelElement).color,
      icon: iconElement === null ? '' : getComputedStyle(iconElement).color,
      chevron: chevronElement === null ? '' : getComputedStyle(chevronElement).color,
      panelLabel: panelLabel === null ? '' : getComputedStyle(panelLabel).color,
      panelValue: panelValue === null ? '' : getComputedStyle(panelValue).color,
    };
  }, label);

  expect(colors.label).toBe(colors.progress);
  expect(colors.icon).toBe(colors.progress);
  expect(colors.chevron).toBe(colors.sub);
  expect(colors.panelLabel).toBe(colors.foreground);
  expect(colors.panelValue).toBe(colors.foreground);

  const panel = frame.getByRole('dialog', { name: '영상 만드는 중' });
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('button')).toHaveCount(0);
});

test('test_10a_top_bar_status_disabled_chevron_uses_the_disabled_color', async ({ page }) => {
  await galleryReady(page, 'top-bar-status', 3);
  const label = labelOf('top-bar-status', 'disabled');
  const frame = await frameOf(page, 'iframe[data-frame-group="top-bar-status"][width="390"]');
  const colors = await frame.evaluate((caseLabel) => {
    const probe = document.createElement('span');
    document.body.append(probe);
    probe.style.color = 'var(--disabled-foreground)';
    const disabled = getComputedStyle(probe).color;
    probe.remove();
    const box = document.querySelector(`[data-case="${caseLabel}"]`);
    const trigger = box?.querySelector('.top-bar-status__trigger') ?? null;
    const chevron = box?.querySelector('.top-bar-status__chevron') ?? null;
    return {
      disabled,
      trigger: trigger === null ? '' : getComputedStyle(trigger).color,
      chevron: chevron === null ? '' : getComputedStyle(chevron).color,
    };
  }, label);

  expect(colors.trigger).toBe(colors.disabled);
  expect(colors.chevron).toBe(colors.disabled);
});

test('test_10a_batch_four_scene_card_shows_the_work_state', async ({ page }) => {
  await galleryReady(page, 'card', 3);
  const frame = await frameOf(page, 'iframe[data-frame-group="card"][width="390"]');
  const label = labelOf('card', 'scene-busy');
  const card = frame.locator(`[data-case="${label}"] .card`);
  await expect(card).toHaveAttribute('data-busy', '');
  await expect(card.locator('.card__status')).toContainText('고치는 중');
  await expect(card.locator('.card__status .spinner')).toHaveCount(1);
  await expect(card.locator('.card__band')).toHaveCount(1);

  const colors = await frame.evaluate((caseLabel) => {
    const probe = document.createElement('span');
    document.body.append(probe);
    const resolve = (name: string) => {
      probe.style.color = `var(${name})`;
      return getComputedStyle(probe).color;
    };
    const emphasis = resolve('--emphasis');
    const progress = resolve('--progress');
    probe.remove();
    const box = document.querySelector(`[data-case="${caseLabel}"]`);
    const cardElement = box?.querySelector('.card') ?? null;
    const statusElement = box?.querySelector('.card__status') ?? null;
    const spinnerElement = box?.querySelector('.card__status .spinner') ?? null;
    return {
      emphasis,
      progress,
      border: cardElement === null ? '' : getComputedStyle(cardElement).borderTopColor,
      status: statusElement === null ? '' : getComputedStyle(statusElement).color,
      spinner: spinnerElement === null ? '' : getComputedStyle(spinnerElement).color,
    };
  }, label);

  expect(colors.border).toBe(colors.emphasis);
  expect(colors.status).toBe(colors.progress);
  expect(colors.spinner).toBe(colors.emphasis);

  const defaultBox = await frame
    .locator(`[data-case="${labelOf('card', 'scene-default')}"] .card`)
    .boundingBox();
  const busyBox = await card.boundingBox();
  expect(busyBox?.width).toBe(defaultBox?.width);
  expect(busyBox?.height).toBe(defaultBox?.height);
});

test('test_10a_batch_four_scroll_surfaces_fade_by_scroll_position', async ({ page }) => {
  await galleryReady(page, 'composer', 2);
  const composer = await frameOf(page, 'iframe[data-frame-group="composer"][width="390"]');
  const composerLabel = labelOf('composer', 'long');
  const field = composer.locator(`[data-case="${composerLabel}"] .composer__field`);
  const input = composer.locator(`[data-case="${composerLabel}"] textarea`);
  await expect(field).toHaveClass(/scroll-fade/);
  await expect(field).toHaveAttribute('data-fade', 'top');
  await input.evaluate((element) => {
    element.scrollTop = 0;
  });
  await expect(field).toHaveAttribute('data-fade', 'bottom');
  await input.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(field).toHaveAttribute('data-fade', 'top');

  await galleryReady(page, 'bottom-sheet', 2);
  const sheet = await frameOf(
    page,
    `iframe[data-frame-case="${labelOf('bottom-sheet', 'long')}"][width="390"]`,
  );
  const sheetFade = sheet.locator('.sheet-popup__scroll-frame');
  const sheetScroll = sheet.locator('.sheet-popup__scroll');
  await expect(sheetFade).toHaveClass(/scroll-fade/);
  await expect(sheetFade).toHaveAttribute('data-fade', 'bottom');
  await sheetScroll.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(sheetFade).toHaveAttribute('data-fade', 'top');

  await galleryReady(page, 'dialog', 2);
  const dialog = await frameOf(
    page,
    `iframe[data-frame-case="${labelOf('dialog', 'long')}"][width="390"]`,
  );
  const dialogFade = dialog.locator('.dialog__scroll-frame');
  const dialogScroll = dialog.locator('.dialog__scroll');
  await expect(dialogFade).toHaveClass(/scroll-fade/);
  await expect(dialogFade).toHaveAttribute('data-fade', 'bottom');
  await dialogScroll.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(dialogFade).toHaveAttribute('data-fade', 'top');
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

test('test_10a_result_card_follows_the_decided_layout', async ({ page }) => {
  const label = labelOf('result-card', 'default');
  const selector = `iframe[data-frame-case="${label}"][width="1920"]`;

  await galleryReady(page, 'result-card', 3);
  const frame = await frameOf(page, selector);
  const dialog = frame.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const heading = frame.getByRole('heading', { level: 2 });
  const title = (await heading.textContent())?.trim() ?? '';
  expect(title).toBeTruthy();
  await expect(heading).toBeVisible();
  await expect(dialog).toHaveAccessibleName(title);

  await expect(frame.getByRole('button', { name: '자막 저장' })).toBeVisible();
  await expect(frame.getByRole('button', { name: '사용량 보기' })).toBeVisible();
  await expect(frame.getByRole('button', { name: '크게 보기' })).toHaveCount(0);
  await expect(frame.getByRole('button', { name: 'SRT 저장' })).toHaveCount(0);
  await expect(frame.getByRole('button', { name: '닫기', exact: true })).toHaveCount(0);
  await expect(frame.locator('.demo-result__facts dt')).toHaveCount(4);

  const actions = frame.locator('.demo-result__actions button');
  await expect(actions).toHaveCount(2);
  await expect(actions.nth(0)).toHaveText('편집으로');
  await expect(actions.nth(1)).toHaveText('mp4 저장');

  const layout = await frame.evaluate(() => {
    const dialog = document.querySelector('[role=dialog]') as HTMLElement;
    const player = document.querySelector('.demo-result__player') as HTMLElement;
    const side = document.querySelector('.demo-result__side') as HTMLElement;
    const video = document.querySelector('.video-preview') as HTMLElement;
    const playback = document.querySelector('.player') as HTMLElement;
    const c = dialog.getBoundingClientRect();
    const p = player.getBoundingClientRect();
    const s = side.getBoundingClientRect();
    const v = video.getBoundingClientRect();
    const play = playback.getBoundingClientRect();
    return {
      playerRight: p.right,
      sideLeft: s.left,
      videoTop: v.top,
      playerTop: p.top,
      playerBottom: p.bottom,
      playbackBottom: play.bottom,
      cardTop: c.top,
      cardBottom: c.bottom,
    };
  });

  expect(layout.playerRight).toBeLessThanOrEqual(layout.sideLeft);
  expect(layout.videoTop).toBe(layout.playerTop);
  expect(layout.playbackBottom).toBe(layout.playerBottom);
  expect(
    Math.abs(layout.playerTop - layout.cardTop - (layout.cardBottom - layout.playerBottom)),
  ).toBeLessThan(1.5);

  const close = frame.getByRole('button', { name: '결과 카드 닫기' });
  await close.focus();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Shift+Tab');
  const ring = await close.evaluate((element) => {
    const style = getComputedStyle(element);
    const button = element.getBoundingClientRect();
    const card = (element.closest('[role=dialog]') as HTMLElement).getBoundingClientRect();
    const offset = Number.parseFloat(style.outlineOffset);
    const width = Number.parseFloat(style.outlineWidth);
    const grow = width + offset;
    return {
      outlineStyle: style.outlineStyle,
      outlineOffset: style.outlineOffset,
      outlineWidth: style.outlineWidth,
      left: button.left - grow,
      top: button.top - grow,
      right: button.right + grow,
      bottom: button.bottom + grow,
      cardLeft: card.left,
      cardTop: card.top,
      cardRight: card.right,
      cardBottom: card.bottom,
    };
  });
  expect(ring.outlineStyle).toBe('solid');
  expect(ring.outlineOffset).toBe('-2px');
  expect(ring.left).toBeGreaterThanOrEqual(ring.cardLeft);
  expect(ring.top).toBeGreaterThanOrEqual(ring.cardTop);
  expect(ring.right).toBeLessThanOrEqual(ring.cardRight);
  expect(ring.bottom).toBeLessThanOrEqual(ring.cardBottom);

  await close.click();
  await expect(dialog).toHaveCount(0);

  await galleryReady(page, 'result-card', 3);
  const reopened = await frameOf(page, selector);
  await reopened.getByRole('button', { name: '결과 카드 닫기' }).press('Escape');
  await expect(reopened.locator('[role=dialog]')).toHaveCount(0);
});

test('test_10a_playback_bar_rounds_both_ends', async ({ page }) => {
  await galleryReady(page, 'playback-controls', 3);
  const frame = await frameOf(page, 'iframe[data-frame-group="playback-controls"][width="390"]');
  const label = labelOf('playback-controls', 'progress');
  const bar = await frame.evaluate((caseLabel) => {
    const box = document.querySelector(`[data-case="${caseLabel}"]`);
    const track = box?.querySelector('.player__track') ?? null;
    const fill = box?.querySelector('.player__fill') ?? null;
    if (track === null || fill === null) return null;
    const trackStyle = getComputedStyle(track);
    const fillStyle = getComputedStyle(fill);
    return {
      trackRadius: Number.parseFloat(trackStyle.borderRadius),
      trackHeight: Number.parseFloat(trackStyle.height),
      fillRadius: Number.parseFloat(fillStyle.borderRadius),
      fillHeight: Number.parseFloat(fillStyle.height),
      fillWidth: Number.parseFloat(fillStyle.width),
    };
  }, label);

  expect(bar).not.toBeNull();
  expect(bar?.trackHeight).toBe(6);
  expect(bar?.fillHeight).toBe(6);
  expect(bar?.trackRadius).toBeGreaterThanOrEqual((bar?.trackHeight ?? 0) / 2);
  expect(bar?.fillRadius).toBeGreaterThanOrEqual((bar?.fillHeight ?? 0) / 2);
  expect(bar?.fillWidth).toBeGreaterThan(0);
});

test('test_10a_scroll_pane_hides_its_scrollbar_and_moves_one_screen', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await galleryReady(page, 'scroll-pane', 3);
  const frame = await frameOf(page, 'iframe[data-frame-group="scroll-pane"][width="390"]');
  const longCase = frame.locator(`[data-case="${labelOf('scroll-pane', 'long')}"]`);
  const viewport = longCase.locator('.scroll-pane__viewport');

  const before = await viewport.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      scrollbarWidth: style.scrollbarWidth,
      overflowY: style.overflowY,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
      scrollTop: element.scrollTop,
    };
  });
  expect(before.scrollbarWidth).toBe('none');
  expect(before.overflowY).toBe('auto');
  expect(before.scrollHeight).toBeGreaterThan(before.clientHeight);

  const jump = longCase.getByRole('button', { name: '아래로 넘기기' });
  await expect(jump).toBeVisible();
  const jumpBox = await jump.boundingBox();
  expect(jumpBox?.width).toBe(44);
  expect(jumpBox?.height).toBe(44);
  expect(
    await jump.evaluate((element) => Number.parseFloat(getComputedStyle(element).borderRadius)),
  ).toBeGreaterThanOrEqual(22);
  await jump.click();
  await page.waitForTimeout(100);
  const moved = await viewport.evaluate((element) => element.scrollTop);
  expect(Math.abs(moved - before.scrollTop - before.clientHeight * 0.8)).toBeLessThan(2);

  await viewport.focus();
  const keyboardStart = await viewport.evaluate((element) => element.scrollTop);
  await viewport.press('ArrowDown');
  await page.waitForTimeout(100);
  expect(await viewport.evaluate((element) => element.scrollTop)).toBeGreaterThan(keyboardStart);

  // Put the end one jump away, then reach it with Enter. The focused control
  // disappears, so the column itself must take focus for the next key.
  await viewport.evaluate((element) => {
    element.scrollTop = element.scrollHeight - element.clientHeight * 1.6;
  });
  await expect(jump).toBeVisible();
  await jump.focus();
  await jump.press('Enter');
  await expect(jump).toHaveCount(0);
  await expect
    .poll(async () => viewport.evaluate((element) => element === document.activeElement))
    .toBe(true);
  const endPosition = await viewport.evaluate((element) => element.scrollTop);
  await viewport.press('ArrowUp');
  await page.waitForTimeout(100);
  expect(await viewport.evaluate((element) => element.scrollTop)).toBeLessThan(endPosition);

  const endCase = frame.locator(`[data-case="${labelOf('scroll-pane', 'end')}"]`);
  await expect(endCase.getByRole('button', { name: '아래로 넘기기' })).toHaveCount(0);
  const shortCase = frame.locator(`[data-case="${labelOf('scroll-pane', 'short')}"]`);
  await expect(shortCase.getByRole('button', { name: '아래로 넘기기' })).toHaveCount(0);
});

test('test_10a_scroll_pane_keyboard_scrolls_while_the_jump_is_focused', async ({ page }) => {
  const opened = await openScrollPane(page);
  await opened.viewport.evaluate((element) => {
    const content = element.firstElementChild;
    if (content === null) throw new Error('missing scroll content');
    const spacer = document.createElement('div');
    spacer.style.height = '1200px';
    content.append(spacer);
    element.scrollTop = 0;
  });
  const pageStart = await page.evaluate(() => window.scrollY);
  await opened.jump.focus();

  // Held arrows must accumulate; a fresh smooth scroll on every key loses most steps.
  for (let index = 0; index < 25; index += 1) await opened.jump.press('ArrowDown');
  await expect
    .poll(async () => opened.viewport.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(900);
  expect(await page.evaluate(() => window.scrollY)).toBe(pageStart);

  const beforeEnter = await opened.viewport.evaluate((element) => element.scrollTop);
  await opened.jump.press('Enter');
  await expect
    .poll(async () => opened.viewport.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(beforeEnter);
  let previous = -1;
  await expect
    .poll(
      async () => {
        const top = await opened.viewport.evaluate((element) => element.scrollTop);
        const settled = top === previous;
        previous = top;
        return settled;
      },
      { timeout: 3_000 },
    )
    .toBe(true);

  await expect(opened.jump).toBeVisible();
  expect(await opened.jump.evaluate((element) => element === document.activeElement)).toBe(true);
  const afterJump = await opened.viewport.evaluate((element) => element.scrollTop);
  await opened.jump.press('ArrowDown');
  await expect
    .poll(async () => opened.viewport.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(afterJump + 20);
  expect(await page.evaluate(() => window.scrollY)).toBe(pageStart);
});

test('test_10a_scroll_pane_keeps_trackpad_and_horizontal_wheel_to_the_browser', async ({ page }) => {
  const open = async (): Promise<ScrollPaneCases> => {
    const opened = await openScrollPane(page);
    await page.evaluate(() => {
      const log: GalleryWheelEvent[] = [];
      window.__galleryWheelLog = log;
      window.addEventListener('wheel', (event) => {
        log.push({
          ctrl: event.ctrlKey,
          shift: event.shiftKey,
          deltaX: event.deltaX,
          deltaY: event.deltaY,
          prevented: event.defaultPrevented,
        });
      });
    });
    return opened;
  };
  const wheel = async (
    opened: ScrollPaneCases,
    target: Locator,
    deltaX: number,
    deltaY: number,
    key?: 'Control' | 'Shift',
  ) => {
    const box = await target.boundingBox();
    if (box === null) throw new Error('missing wheel target');
    const before = await opened.viewport.evaluate((element) => element.scrollTop);
    const scaleBefore = await page.evaluate(() => window.visualViewport?.scale ?? 1);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    if (key !== undefined) await page.keyboard.down(key);
    await page.mouse.wheel(deltaX, deltaY);
    if (key !== undefined) await page.keyboard.up(key);
    await page.waitForTimeout(150);
    const after = await opened.viewport.evaluate((element) => element.scrollTop);
    const scaleAfter = await page.evaluate(() => window.visualViewport?.scale ?? 1);
    const last = await page.evaluate(() => window.__galleryWheelLog?.at(-1) ?? null);
    return { before, after, scaleBefore, scaleAfter, last };
  };

  // A control or shift wheel over the jump must reach the browser. The body
  // baseline may zoom or scroll in the browser; the control must not decide,
  // and the jump only checks that the column itself stays put.
  const controlBody = await open();
  const bodyResult = await wheel(controlBody, controlBody.body, 0, 120, 'Control');
  expect(bodyResult.last?.ctrl).toBe(true);
  expect(bodyResult.last?.prevented).toBe(false);
  expect(
    bodyResult.scaleAfter !== bodyResult.scaleBefore || bodyResult.after !== bodyResult.before,
  ).toBe(true);
  const bodyZoomed = bodyResult.scaleAfter !== bodyResult.scaleBefore;

  const controlJump = await open();
  const controlResult = await wheel(controlJump, controlJump.jump, 0, 120, 'Control');
  expect(controlResult.last?.ctrl).toBe(true);
  expect(controlResult.last?.prevented).toBe(false);
  expect(controlResult.after).toBe(controlResult.before);
  // When the browser zooms the body, the gesture over the jump must zoom too.
  if (bodyZoomed) expect(controlResult.scaleAfter).not.toBe(controlResult.scaleBefore);

  const shiftJump = await open();
  const shiftResult = await wheel(shiftJump, shiftJump.jump, 0, 120, 'Shift');
  expect(shiftResult.last?.shift).toBe(true);
  expect(shiftResult.last?.prevented).toBe(false);
  expect(shiftResult.after).toBe(shiftResult.before);

  const horizontalJump = await open();
  const horizontalResult = await wheel(horizontalJump, horizontalJump.jump, 120, 0);
  expect(horizontalResult.last?.deltaX).toBeGreaterThan(0);
  expect(horizontalResult.last?.prevented).toBe(false);
  expect(horizontalResult.after).toBe(horizontalResult.before);
});

test('test_10a_scroll_pane_zoom_over_the_body_keeps_the_column', async ({ page }) => {
  const opened = await openScrollPane(page);
  const client = await page.context().newCDPSession(page);
  await opened.viewport.evaluate((element) => {
    element.style.scrollBehavior = 'auto';
    element.scrollTop = 118;
  });
  const box = await opened.viewport.boundingBox();
  if (box === null) throw new Error('missing body zoom target');
  const before = await opened.viewport.evaluate((element) => element.scrollTop);
  const scaleBefore = await page.evaluate(() => window.visualViewport?.scale ?? 1);
  await client.send('Input.synthesizePinchGesture', {
    x: box.x + box.width / 2,
    y: box.y + box.height / 2,
    scaleFactor: 1.3,
    relativeSpeed: 800,
    gestureSourceType: 'mouse',
  });
  await page.waitForTimeout(600);
  const scaleAfter = await page.evaluate(() => window.visualViewport?.scale ?? 1);
  const after = await opened.viewport.evaluate((element) => element.scrollTop);
  expect(scaleAfter).toBeGreaterThan(scaleBefore);
  expect(after).toBe(before);
});

test('test_10a_scroll_pane_zoom_over_the_jump_keeps_the_column', async ({ page }) => {
  const opened = await openScrollPane(page);
  const client = await page.context().newCDPSession(page);
  await opened.viewport.evaluate((element) => {
    element.style.scrollBehavior = 'auto';
    element.scrollTop = 118;
  });
  const box = await opened.jump.boundingBox();
  if (box === null) throw new Error('missing jump zoom target');
  const before = await opened.viewport.evaluate((element) => element.scrollTop);
  const scaleBefore = await page.evaluate(() => window.visualViewport?.scale ?? 1);
  await client.send('Input.synthesizePinchGesture', {
    x: box.x + box.width / 2,
    y: box.y + box.height / 2,
    scaleFactor: 1.3,
    relativeSpeed: 800,
    gestureSourceType: 'mouse',
  });
  await page.waitForTimeout(600);
  const scaleAfter = await page.evaluate(() => window.visualViewport?.scale ?? 1);
  const after = await opened.viewport.evaluate((element) => element.scrollTop);
  expect(scaleAfter).toBeGreaterThan(scaleBefore);
  expect(after).toBe(before);
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
  expect(format[0][0]).toBe(216);
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
