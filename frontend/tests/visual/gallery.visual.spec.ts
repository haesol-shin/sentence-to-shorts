import { expect, test, type Page } from '@playwright/test';

import { galleryParts, inlineCases, portalCases } from '../../src/gallery/items';

/**
 * The gallery is the design source, so every part, state and width has one
 * screenshot baseline here. The baselines are drawn on the GitHub Actions
 * runner only: `PLAYWRIGHT_VISUAL=1 npx playwright test tests/visual
 * --update-snapshots` writes them, and the visual job fails until that output
 * is committed to the same branch.
 */
const GALLERY = '/src/gallery/index.html';
const WIDTHS = [
  { width: 390, height: 844 },
  { width: 1920, height: 1080 },
] as const;
/** Menus, tooltips, windows and other surfaces that open over the part. */
const SURFACES =
  '.menu-positioner, .field-positioner, .tooltip-positioner, .status-positioner, .dialog, .sheet-popup, .toast-surface, .file-drop';

test.describe.configure({ mode: 'parallel', timeout: 180_000 });

async function openGallery(page: Page, query: string, cases: number): Promise<void> {
  await page.goto(`${GALLERY}?${query}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.waitForFunction(
    (count) => document.querySelectorAll('[data-case]').length === count,
    cases,
    { timeout: 120_000 },
  );
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
}

for (const part of galleryParts) {
  test(`test_23_gallery_matches_the_baseline_${part.id}`, async ({ page }) => {
    // Transitions and spinners settle at once under the reduced motion tokens.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const inline = inlineCases(part);
    for (const { width, height } of WIDTHS) {
      await page.setViewportSize({ width, height });
      if (inline.length > 0) {
        await openGallery(page, `group=${encodeURIComponent(part.id)}`, inline.length);
        for (const entry of inline) {
          await expect(page.locator(`[data-case="${entry.label}"]`)).toHaveScreenshot(
            `${part.id}--${entry.label}-${width}.png`,
          );
        }
      }
      for (const entry of portalCases(part)) {
        await openGallery(page, `case=${encodeURIComponent(entry.label)}`, 1);
        const surface = page.locator(SURFACES).filter({ visible: true }).first();
        await expect(surface).toBeVisible();
        await expect(surface).toHaveScreenshot(`${part.id}--${entry.label}-${width}.png`);
      }
    }
  });
}
