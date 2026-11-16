import type { Page, TestInfo } from '@playwright/test';

/**
 * Writes a pull request capture from the Chromium projects only. The WebKit
 * projects run the same tests at the same width, and the iPhone 13 device
 * renders at scale 3, so a WebKit run would overwrite the file with a larger
 * image whenever it finished last.
 */
export async function capture(page: Page, testInfo: TestInfo, path: string, fullPage = false): Promise<void> {
  if (testInfo.project.use.browserName !== 'chromium') return;
  await page.screenshot({ path, fullPage });
}
