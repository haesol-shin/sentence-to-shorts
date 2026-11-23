import { expect, test, type Page } from '@playwright/test';

const EXPORT_STAGE = '[data-slot="stage-panel"][data-stage="export"]';

/** Opens a step from the stage menu, or from the indicator when the menu is not drawn. */
async function openStage(page: Page, label: string): Promise<void> {
  const menu = page.getByRole('button', { name: '단계 열기' });
  if (await menu.isVisible()) {
    await menu.click();
    await page.getByRole('menuitem', { name: label, exact: true }).click();
    return;
  }
  await page
    .locator('[data-slot="stage-indicator"]')
    .getByRole('button', { name: label, exact: true })
    .click();
}

/**
 * Runs a click that saves a file and returns the saved name and bytes. The link
 * the page clicks is read instead of the browser's download, so engines that
 * cancel headless downloads still prove the file the page offers.
 */
async function saveFile(
  page: Page,
  click: () => Promise<void>,
): Promise<{ name: string; bytes: number[] }> {
  const saved = page.evaluate(
    () =>
      new Promise<{ name: string; bytes: number[] }>((resolve, reject) => {
        const onClick = (event: Event) => {
          const link = event.target;
          if (!(link instanceof HTMLAnchorElement) || link.download === '') return;
          document.removeEventListener('click', onClick, true);
          event.preventDefault();
          fetch(link.href)
            .then(async (response) => resolve({ name: link.download, bytes: Array.from(new Uint8Array(await response.arrayBuffer())) }))
            .catch(reject);
        };
        document.addEventListener('click', onClick, true);
      }),
  );
  await click();
  return saved;
}

test('the result plays and saves a video and timed captions', async ({ page }) => {
  await page.goto('/');
  await page
    .getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })
    .fill('색이 다른 사각형의 움직임');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();
  await openStage(page, '편집');
  await expect(page.locator('[data-slot="scene-column"] [data-slot="scene-card"]')).toHaveCount(5);

  const nextAction = page.locator('[data-slot="top-bar"] [data-slot="next-action"]');
  await nextAction.click();
  await page
    .getByRole('dialog', { name: '장면 확인' })
    .getByRole('button', { name: '영상 만들기' })
    .click();
  const stage = page.locator(EXPORT_STAGE);
  await stage.locator('[data-slot="export-start"]').click();

  const card = page.getByRole('dialog', { name: '영상', exact: true });
  await expect(card).toBeVisible({ timeout: 20_000 });
  const video = card.locator('[data-slot="result-video"]');
  // A headless engine without an H.264 decoder cannot play the clip; the saved bytes below still prove the file.
  const canPlay = await video.evaluate(
    (node) => (node as HTMLVideoElement).canPlayType('video/mp4; codecs="avc1.42E01E"') !== '',
  );
  if (canPlay) {
    await card.getByRole('button', { name: '재생', exact: true }).click();
    await expect.poll(() => video.evaluate((node) => (node as HTMLVideoElement).currentTime)).toBeGreaterThan(0.25);
  }
  const sourceBytes = await video.evaluate(async (node) => {
    const response = await fetch((node as HTMLVideoElement).currentSrc);
    return Array.from(new Uint8Array(await response.arrayBuffer()));
  });
  await card.getByRole('button', { name: '결과 카드 닫기' }).click();
  await expect(card).toBeHidden();
  // Closing the card lands on the edit step, so the export panel is opened again for the save controls.
  await openStage(page, '내보내기');
  await expect(stage).toBeVisible();

  const mp4 = await saveFile(page, () => nextAction.click());
  expect(mp4.name).toBe('example.mp4');
  expect(Buffer.from(mp4.bytes).toString('ascii', 4, 8)).toBe('ftyp');
  expect(mp4.bytes).toEqual(sourceBytes);

  const srt = await saveFile(page, () => stage.getByRole('button', { name: '자막 저장' }).click());
  expect(srt.name).toBe('example.srt');
  expect(Buffer.from(srt.bytes).toString('utf8')).toBe(
    '1\n00:00:00,000 --> 00:00:01,500\n사각형이 왼쪽에서 나타나요.\n\n' +
      '2\n00:00:01,500 --> 00:00:03,000\n사각형이 오른쪽으로 움직여요.\n',
  );
});
