import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

import {
  GALLERY_SURFACES,
  HIT_AREA_PART_IDS,
  findPart,
  inlineCases,
  portalCases,
} from '../../src/gallery/items';
import { measureFrame, type HitAreaRow, type MeasuredControl, type MeasuredOverlap } from './measure';

const GALLERY = '/src/gallery/index.html';
/** The record this test compares with. `HIT_AREA_RECORD=1` rewrites it after a reviewed change. */
const RECORD = join(process.cwd(), 'tests', 'gallery', 'hit-area.json');
const WIDTHS = [1280, 1920] as const;

type Measured = MeasuredControl & { part: string; width: number };
type MeasuredOverlapPart = MeasuredOverlap & { part: string; width: number };

test.describe.configure({ mode: 'serial', timeout: 300_000 });

// eslint-disable-next-line no-empty-pattern
test.beforeEach(({}, testInfo) => {
  test.skip(
    testInfo.project.name !== 'chromium-desktop',
    'one chromium measurement keeps the recorded boxes comparable',
  );
});

async function open(page: Page, query: string, cases: number): Promise<void> {
  await page.goto(`${GALLERY}?${query}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.waitForFunction((count) => document.querySelectorAll('[data-case]').length === count, cases, {
    timeout: 120_000,
  });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await page.waitForTimeout(150);
}

test('test_10a_batch_two_hit_areas_match_the_record', async ({ page }) => {
  const measured: Measured[] = [];
  const overlapsAll: MeasuredOverlapPart[] = [];
  for (const partId of HIT_AREA_PART_IDS) {
    const part = findPart(partId);
    if (part === undefined) throw new Error(`missing part: ${partId}`);
    const inline = inlineCases(part);
    if (inline.length > 0) {
      for (const width of WIDTHS) {
        // A tall viewport fits the whole group. A scrolled page would put two cases on the
        // same viewport coordinates and invent an overlap between controls that never meet.
        await page.setViewportSize({ width, height: 2400 });
        await open(page, `group=${encodeURIComponent(part.id)}`, inline.length);
        const result = await page.evaluate(measureFrame, { fallbackCase: '', declaredRing: false });
        for (const control of result.controls) measured.push({ ...control, part: part.id, width });
        for (const overlap of result.overlapsAll) overlapsAll.push({ ...overlap, part: part.id, width });
      }
    }
    for (const entry of portalCases(part)) {
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 1080 });
        await open(page, `case=${encodeURIComponent(entry.label)}`, 1);
        await expect(page.locator(GALLERY_SURFACES).filter({ visible: true }).first()).toBeVisible();
        await page.waitForTimeout(250);
        const result = await page.evaluate(measureFrame, {
          fallbackCase: entry.label,
          declaredRing: false,
        });
        for (const control of result.controls) measured.push({ ...control, part: part.id, width });
        for (const overlap of result.overlapsAll) overlapsAll.push({ ...overlap, part: part.id, width });
      }
    }
  }

  const parts: Record<string, Record<string, HitAreaRow[]>> = {};
  for (const partId of HIT_AREA_PART_IDS) {
    const byWidth: Record<string, HitAreaRow[]> = {};
    for (const width of WIDTHS) {
      byWidth[String(width)] = measured
        .filter((control) => control.part === partId && control.width === width)
        .map((control) => ({
          case: control.case,
          role: control.role,
          name: control.name,
          disabled: control.disabled,
          covered: control.covered,
          visible: [Math.floor(control.visible.width), Math.floor(control.visible.height)],
          hit: [Math.floor(control.hit.width), Math.floor(control.hit.height)],
        }));
    }
    parts[partId] = byWidth;
  }
  const record = {
    method:
      'elementFromPoint probes in 0.5px steps around every visible control and at points inside it. The record holds the box the browser actually delivers, without adding a CSS declared size, so a clipped or covered control cannot pass. A control still clipped after scrolling stays in the rows as a covered row with a zero hit area. Overlap is compared in document coordinates after any scroll. Measured in the gallery at 1280 and 1920. Sizes are floored to whole CSS pixels so a half pixel boundary cannot move the record.',
    widths: WIDTHS,
    parts,
  };
  if (process.env.HIT_AREA_RECORD === '1') {
    writeFileSync(RECORD, `${JSON.stringify(record, null, 2)}\n`);
  } else {
    const committed = JSON.parse(readFileSync(RECORD, 'utf8')) as typeof record;
    expect(committed.widths).toEqual(record.widths);
    expect(committed.parts).toEqual(record.parts);
  }

  expect(measured.length).toBeGreaterThan(0);
  expect(measured.filter((control) => control.covered)).toEqual([]);
  expect(measured.filter((control) => control.hit.width < 44 || control.hit.height < 44)).toEqual([]);
  expect(overlapsAll).toEqual([]);
});

test('test_10a_batch_two_hit_area_coverings_fail', async ({ page }) => {
  const part = findPart('send-button');
  if (part === undefined) throw new Error('missing part: send-button');
  await page.setViewportSize({ width: 1280, height: 1080 });
  await open(page, `group=${part.id}`, inlineCases(part).length);
  const send = page.locator('[data-case="17-1-default"] button[aria-label="보내기"]');
  await expect(send).toHaveCount(1);

  const sendBox = async () => {
    const result = await page.evaluate(measureFrame, {
      fallbackCase: '17-1-default',
      declaredRing: false,
    });
    const row = result.controls.find(
      (control) => control.case === '17-1-default' && control.name === '보내기',
    );
    if (row === undefined) throw new Error('missing send button row');
    return row;
  };
  const addCover = async (name: string, left: number, top: number, width: number, height: number) => {
    await send.evaluate(
      (element, cover) => {
        const rect = element.getBoundingClientRect();
        const overlay = document.createElement('div');
        overlay.dataset.cover = cover.name;
        overlay.style.position = 'fixed';
        overlay.style.left = `${rect.left + rect.width / 2 + cover.left}px`;
        overlay.style.top = `${rect.top + rect.height / 2 + cover.top}px`;
        overlay.style.width = `${cover.width}px`;
        overlay.style.height = `${cover.height}px`;
        overlay.style.background = 'rgba(0,0,0,0.01)';
        overlay.style.zIndex = '10000';
        overlay.style.pointerEvents = 'auto';
        document.body.append(overlay);
      },
      { name, left, top, width, height },
    );
  };

  expect((await sendBox()).covered).toBe(false);
  for (const cover of [
    { name: 'center', left: -15, top: -15, width: 30, height: 30 },
    { name: 'corridor', left: -22, top: -2, width: 40, height: 4 },
    { name: 'band', left: -22, top: -2, width: 44, height: 4 },
  ]) {
    await addCover(cover.name, cover.left, cover.top, cover.width, cover.height);
    expect((await sendBox()).covered, cover.name).toBe(true);
    await page.evaluate(() => document.querySelectorAll('[data-cover]').forEach((node) => node.remove()));
  }
});

test('test_10a_clipped_controls_fail_the_record', async ({ page }) => {
  const part = findPart('send-button');
  if (part === undefined) throw new Error('missing part: send-button');
  await page.setViewportSize({ width: 1280, height: 1080 });
  await open(page, `group=${part.id}`, inlineCases(part).length);
  await page.locator('[data-case="17-1-default"]').evaluate((container) => {
    const clip = document.createElement('div');
    clip.style.position = 'absolute';
    clip.style.width = '5px';
    clip.style.height = '5px';
    clip.style.overflow = 'hidden';
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-label', '잘린 단추');
    button.textContent = '잘린';
    button.style.width = '44px';
    button.style.height = '44px';
    clip.append(button);
    container.append(clip);
  });
  const result = await page.evaluate(measureFrame, {
    fallbackCase: '17-1-default',
    declaredRing: false,
  });
  const row = result.controls.find((control) => control.name === '잘린 단추');
  if (row === undefined) throw new Error('missing clipped row');
  expect(row.case).toBe('17-1-default');
  expect(row.covered).toBe(true);
  expect(row.hit).toEqual({ width: 0, height: 0 });
  expect(result.clipped).toBe(1);
});
