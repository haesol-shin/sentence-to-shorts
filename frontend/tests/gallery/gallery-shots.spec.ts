import { existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type Frame, type Page } from '@playwright/test';

import { galleryParts, galleryRanges, inlineCases, portalCases } from '../../src/gallery/items';
import { measureFrame, type MeasuredControl, type MeasuredOverlap } from './measure';

const GALLERY = '/src/gallery/index.html';
const SHOTS = process.env.GALLERY_SHOTS_DIR ?? join(process.cwd(), 'test-results', 'gallery-shots');
const GALLERY_SHEETS = join(SHOTS, 'gallery');

// eslint-disable-next-line no-empty-pattern
test.beforeEach(({}, testInfo) => {
  test.skip(
    testInfo.project.name !== 'chromium-desktop',
    'one browser produces the reviewed gallery evidence',
  );
});

async function galleryReady(page: Page): Promise<void> {
  // Tall enough that a cropped popup near a frame edge keeps its margin.
  await page.setViewportSize({ width: 2400, height: 1600 });
  await page.goto(`${GALLERY}?batch=2`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.waitForFunction(
    (count) => document.querySelectorAll('[data-part]').length === count,
    galleryParts.filter((part) => part.batch === 2).length,
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
  testInfo.setTimeout(600_000);
  mkdirSync(SHOTS, { recursive: true });
  mkdirSync(GALLERY_SHEETS, { recursive: true });
  for (const name of readdirSync(SHOTS)) {
    if (name.endsWith('.png')) rmSync(join(SHOTS, name), { force: true });
  }

  await galleryReady(page);
  await page.screenshot({ path: join(GALLERY_SHEETS, 'gallery-overview.png') });

  for (const part of galleryParts.filter((candidate) => candidate.batch === 2)) {
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
        await frame.evaluate(() => {
          const active = document.activeElement;
          if (active instanceof HTMLElement) active.blur();
        });
        await iframe.scrollIntoViewIfNeeded();
        const frameBox = await iframe.boundingBox();
        if (frameBox === null) throw new Error(`missing frame box: ${selector}`);
        const area = await frame.evaluate(() => {
          const boxOf = (element: Element | null) => {
            if (element === null) return null;
            const box = element.getBoundingClientRect();
            return { left: box.left, top: box.top, right: box.right, bottom: box.bottom };
          };
          const caseBox = boxOf(document.querySelector('[data-case]'));
          const popups = [
            ...document.querySelectorAll(
              '.menu-positioner, .field-positioner, .tooltip-positioner, .dialog, .sheet-popup, .toast-surface, .file-drop',
            ),
          ]
            .map((element) => boxOf(element))
            .filter((box): box is { left: number; top: number; right: number; bottom: number } => box !== null);
          const boxes = [caseBox, ...popups].filter(
            (box): box is { left: number; top: number; right: number; bottom: number } => box !== null,
          );
          return {
            left: Math.max(0, Math.min(...boxes.map((box) => box.left)) - 24),
            top: Math.max(0, Math.min(...boxes.map((box) => box.top)) - 24),
            right: Math.min(window.innerWidth, Math.max(...boxes.map((box) => box.right)) + 24),
            bottom: Math.min(window.innerHeight, Math.max(...boxes.map((box) => box.bottom)) + 24),
          };
        });
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

  for (const part of galleryParts.filter((candidate) => candidate.batch === 2)) {
    for (const entry of part.cases) {
      for (const width of [390, 1920] as const) {
        expect(existsSync(join(SHOTS, `${entry.label}-${width}.png`)), `${entry.label}-${width}`).toBe(true);
      }
    }
  }

  const controls: (MeasuredControl & { part: string; width: number })[] = [];
  const overlaps: (MeasuredOverlap & { part: string; width: number })[] = [];
  let clipped = 0;
  for (const part of galleryParts.filter((candidate) => candidate.batch === 2)) {
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

  for (const range of galleryRanges.filter((candidate) =>
    candidate.parts.some((part) => part.batch === 2),
  )) {
    await page.locator(`[data-range="${range.id}"]`).screenshot({
      path: join(GALLERY_SHEETS, `gallery-parts-${range.id}.png`),
    });
  }
});
