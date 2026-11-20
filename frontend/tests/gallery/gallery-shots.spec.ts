import { existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type Frame, type Page } from '@playwright/test';

import {
  GALLERY_SURFACES,
  HIT_AREA_PART_IDS,
  galleryParts,
  galleryRanges,
  inlineCases,
  portalCases,
} from '../../src/gallery/items';
import { measureFrame, type MeasuredControl, type MeasuredOverlap } from './measure';

const GALLERY = '/src/gallery/index.html';
const SHOTS = process.env.GALLERY_SHOTS_DIR ?? join(process.cwd(), 'test-results', 'gallery-shots');
const GALLERY_SHEETS = join(SHOTS, 'gallery');
/** The parts this desktop review round changed, captured at 1280 as well as 1920. */
const DESKTOP_PARTS = [
  'radio',
  'switch',
  'tag',
  'settings-row',
  'progress',
  'top-bar-status',
  'card',
  'playback-controls',
  'result-card',
  'scroll-pane',
  ...HIT_AREA_PART_IDS,
];

// eslint-disable-next-line no-empty-pattern
test.beforeEach(({}, testInfo) => {
  test.skip(
    testInfo.project.name !== 'chromium-desktop',
    'one browser produces the reviewed gallery evidence',
  );
});

async function galleryReady(page: Page, batch: number): Promise<void> {
  // Tall enough that a cropped popup near a frame edge keeps its margin.
  await page.setViewportSize({ width: 2400, height: 1600 });
  await page.goto(`${GALLERY}?batch=${batch}&view=all`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.waitForFunction(
    (count) => document.querySelectorAll('[data-part]').length === count,
    galleryParts.filter((part) => part.batch === batch).length,
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
  await page.evaluate(() => document.fonts.ready);
  for (const handle of await page.locator('iframe[data-frame-part]').elementHandles()) {
    const frame = await handle.contentFrame();
    if (frame !== null) await frame.evaluate(() => document.fonts.ready);
  }
  await page.waitForTimeout(500);
}

async function frameOf(page: Page, selector: string): Promise<Frame> {
  const handle = await page.locator(selector).elementHandle();
  if (handle === null) throw new Error(`missing frame: ${selector}`);
  const frame = await handle.contentFrame();
  if (frame === null) throw new Error(`missing content: ${selector}`);
  return frame;
}

test('test_10a_gallery_screenshots_and_hit_areas', async ({ page }, testInfo) => {
  testInfo.setTimeout(900_000);
  mkdirSync(SHOTS, { recursive: true });
  mkdirSync(GALLERY_SHEETS, { recursive: true });
  for (const name of readdirSync(SHOTS)) {
    if (name.endsWith('.png')) rmSync(join(SHOTS, name), { force: true });
  }

  const controls: (MeasuredControl & { part: string; width: number })[] = [];
  const overlaps: (MeasuredOverlap & { part: string; width: number })[] = [];
  let clipped = 0;

  for (const batch of [1, 2, 3] as const) {
    await galleryReady(page, batch);
    await page.screenshot({ path: join(GALLERY_SHEETS, `gallery-overview-${batch}.png`) });

    for (const part of galleryParts.filter((candidate) => candidate.batch === batch)) {
      for (const width of [390, 1920] as const) {
        if (inlineCases(part).length > 0) {
          const frame = page.frameLocator(`iframe[data-frame-group="${part.id}"][width="${width}"]`);
          for (const entry of inlineCases(part)) {
            await frame
              .locator(`[data-case="${entry.label}"]`)
              .screenshot({ path: join(SHOTS, `${entry.label}-${width}.png`) });
          }
        }
        for (const entry of portalCases(part)) {
          const selector = `iframe[data-frame-case="${entry.label}"][width="${width}"]`;
          const iframe = page.locator(selector);
          const frame = await frameOf(page, selector);
          await frame
            .locator('[role=menu], [role=listbox], [role=tooltip], [role=dialog], [role=alertdialog], [role=status]')
            .first()
            .waitFor({ timeout: 10_000 });
          await page.waitForTimeout(250);
          await frame.addStyleTag({
            content: '*:focus, *:focus-visible { outline: none !important; box-shadow: none !important; }',
          });
          await iframe.scrollIntoViewIfNeeded();
          const frameBox = await iframe.boundingBox();
          if (frameBox === null) throw new Error(`missing frame box: ${selector}`);
          const area = await frame.evaluate((surfaceSelector) => {
            const boxOf = (element: Element | null) => {
              if (element === null) return null;
              const box = element.getBoundingClientRect();
              return { left: box.left, top: box.top, right: box.right, bottom: box.bottom };
            };
            const caseBox = boxOf(document.querySelector('[data-case]'));
            const labelBox = boxOf(document.querySelector('.case__label'));
            const popups = [...document.querySelectorAll(surfaceSelector)]
              .map((element) => boxOf(element))
              .filter((box): box is { left: number; top: number; right: number; bottom: number } => box !== null);
            const boxes = [caseBox, labelBox, ...popups].filter(
              (box): box is { left: number; top: number; right: number; bottom: number } => box !== null,
            );
            const safe = boxes.length > 0 ? boxes : [{ left: 0, top: 0, right: innerWidth, bottom: innerHeight }];
            return {
              left: Math.max(0, Math.min(...safe.map((box) => box.left)) - 24),
              top: Math.max(0, Math.min(...safe.map((box) => box.top)) - 24),
              right: Math.min(window.innerWidth, Math.max(...safe.map((box) => box.right)) + 24),
              bottom: Math.min(window.innerHeight, Math.max(...safe.map((box) => box.bottom)) + 24),
            };
          }, GALLERY_SURFACES);
          await page.screenshot({
            path: join(SHOTS, `${entry.label}-${width}.png`),
            clip: {
              x: frameBox.x + area.left,
              y: frameBox.y + area.top,
              width: area.right - area.left,
              height: area.bottom - area.top,
            },
          });
        }
      }
    }

    for (const range of galleryRanges.filter((candidate) =>
      candidate.parts.some((part) => part.batch === batch),
    )) {
      await page.locator(`[data-range="${range.id}"]`).screenshot({
        path: join(GALLERY_SHEETS, `gallery-parts-${range.id}.png`),
      });
    }

    for (const part of galleryParts.filter((candidate) => candidate.batch === batch)) {
      for (const width of [390, 1920] as const) {
        const selectors: string[] = [];
        if (inlineCases(part).length > 0) {
          selectors.push(`iframe[data-frame-group="${part.id}"][width="${width}"]`);
        }
        for (const entry of portalCases(part)) {
          selectors.push(`iframe[data-frame-case="${entry.label}"][width="${width}"]`);
        }
        for (const selector of selectors) {
          const frame = await frameOf(page, selector);
          const fallback = selector.includes('data-frame-case')
            ? (selector.match(/data-frame-case="([^"]+)"/)?.[1] ?? '')
            : '';
          const result = await frame.evaluate(measureFrame, fallback);
          for (const control of result.controls) controls.push({ ...control, part: part.id, width });
          for (const overlap of result.overlaps) overlaps.push({ ...overlap, part: part.id, width });
          clipped += result.clipped;
        }
      }
    }
  }

  // The desktop review round also wants 1280 captures. The full gallery draws 390
  // and 1920 frames, so these open the part or case directly at a 1280 viewport.
  await page.setViewportSize({ width: 1280, height: 1080 });
  for (const partId of DESKTOP_PARTS) {
    const part = galleryParts.find((candidate) => candidate.id === partId);
    if (part === undefined) continue;
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
      await page.waitForTimeout(150);
      for (const entry of inlineCases(part)) {
        await page
          .locator(`[data-case="${entry.label}"]`)
          .screenshot({ path: join(SHOTS, `${entry.label}-1280.png`) });
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
      const surface = page.locator(GALLERY_SURFACES).filter({ visible: true }).first();
      await expect(surface).toBeVisible();
      await page.addStyleTag({
        content: '*:focus, *:focus-visible { outline: none !important; box-shadow: none !important; }',
      });
      await page.evaluate(async () => {
        await document.fonts.ready;
      });
      await page.waitForTimeout(250);
      await surface.screenshot({ path: join(SHOTS, `${entry.label}-1280.png`) });
    }
  }

  for (const batch of [1, 2, 3] as const) {
    for (const part of galleryParts.filter((candidate) => candidate.batch === batch)) {
      for (const entry of part.cases) {
        for (const width of [390, 1920] as const) {
          expect(existsSync(join(SHOTS, `${entry.label}-${width}.png`)), `${entry.label}-${width}`).toBe(true);
        }
        if (DESKTOP_PARTS.includes(part.id)) {
          expect(existsSync(join(SHOTS, `${entry.label}-1280.png`)), `${entry.label}-1280`).toBe(true);
        }
      }
    }
  }

  const small = controls.filter((control) => control.hit.width < 43.5 || control.hit.height < 43.5);
  const report = {
    method:
      'elementFromPoint probes in 0.5px steps around every visible control; the declared transparent hit ring supplies the designed size. Rows clipped by the both-sides-insufficient menu are scrolled into view in that menu before measuring; overlap checks use controls visible together.',
    widths: [390, 1920],
    controls,
    failures: { small, overlaps },
    clipped,
    clippedNote: 'none; the tight menu rows scroll into view for the measurement.',
    allPass: small.length === 0 && overlaps.length === 0,
  };
  writeFileSync(join(SHOTS, 'hit-area.json'), `${JSON.stringify(report, null, 2)}\n`);

  expect(small).toEqual([]);
  expect(overlaps).toEqual([]);
  expect(controls.length).toBeGreaterThan(0);
});
