import { expect, test } from '@playwright/test';

import { galleryParts } from '../../src/gallery/items';

const GALLERY = '/src/gallery/index.html';

test.describe.configure({ mode: 'serial', timeout: 180_000 });

function labelOf(partId: string, slug: string): string {
  const part = galleryParts.find((candidate) => candidate.id === partId);
  const entry = part?.cases.find((candidate) => candidate.slug === slug);
  if (entry === undefined) throw new Error(`missing case: ${partId} ${slug}`);
  return entry.label;
}

// The plain wheel is component input, not gallery evidence, so it runs in
// every project. Mobile WebKit is the exception: Playwright rejects
// page.mouse.wheel there because the iPhone emulation has no mouse wheel.
test('test_10a_scroll_pane_moves_with_a_plain_wheel', async ({ page, browserName, isMobile }) => {
  test.skip(browserName === 'webkit' && isMobile, 'mobile WebKit has no page.mouse.wheel');
  for (const targetName of ['body', 'jump'] as const) {
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
    const viewport = longCase.locator('.scroll-pane__viewport');
    const target =
      targetName === 'jump'
        ? longCase.getByRole('button', { name: '아래로 넘기기' })
        : longCase.locator('.demo-scroll-pane__line').first();
    const box = await target.boundingBox();
    if (box === null) throw new Error(`missing wheel target: ${targetName}`);
    const before = await viewport.evaluate((element) => element.scrollTop);

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, 120);
    await expect
      .poll(async () => viewport.evaluate((element) => element.scrollTop))
      .toBeGreaterThan(before + 100);
  }
});
