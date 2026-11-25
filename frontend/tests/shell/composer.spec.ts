import { expect, test, type Locator, type Page } from '@playwright/test';

const FIRST_COMPOSER = '[data-slot="first-screen"] [data-slot="composer"]';
const SENTENCE = '별이 보이는 이유';

function lines(count: number): string {
  return Array.from({ length: count }, (_, index) => `${index + 1}번째 줄`).join('\n');
}

async function openFirst(page: Page): Promise<Locator> {
  await page.goto('/');
  const composer = page.locator(FIRST_COMPOSER);
  await expect(composer).toBeVisible();
  return composer;
}

async function startConcept(page: Page): Promise<void> {
  await page.goto('/');
  await page
    .getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })
    .fill(SENTENCE);
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  await expect(page.getByRole('heading', { name: '컨셉', exact: true })).toBeVisible();
}

function stageComposer(page: Page): Locator {
  const width = page.viewportSize()?.width ?? 0;
  return page.locator(
    width < 768 ? '[data-slot="composer-dock"] [data-slot="composer"]' : '[data-slot="conversation"] [data-slot="composer"]',
  );
}

function filePayload(name: string, type: string, text: string) {
  return { name, mimeType: type, buffer: Buffer.from(text) };
}

test('test_10a_the_text_field_is_full_width_and_stops_at_ten_lines', async ({ page }) => {
  const composer = await openFirst(page);
  const textarea = composer.locator('textarea');

  const styles = await textarea.evaluate((node) => {
    const computed = getComputedStyle(node);
    return { font: computed.fontSize, line: computed.lineHeight };
  });
  expect(styles).toEqual({ font: '17px', line: '24px' });

  const composerBox = await composer.boundingBox();
  const textBox = await textarea.boundingBox();
  expect(composerBox).not.toBeNull();
  expect(textBox).not.toBeNull();
  if (composerBox === null || textBox === null) return;
  expect(textBox.width).toBeGreaterThanOrEqual(composerBox.width - 30);

  await textarea.fill(lines(10));
  await expect
    .poll(async () => Math.round((await textarea.boundingBox())?.height ?? 0))
    .toBe(260);
  expect(await textarea.evaluate((node) => getComputedStyle(node).maskImage)).toBe('none');

  await textarea.fill(lines(9));
  expect(await textarea.evaluate((node) => getComputedStyle(node).maskImage)).toBe('none');

  await textarea.fill(lines(11));
  await expect
    .poll(async () => Math.round((await textarea.boundingBox())?.height ?? 0))
    .toBe(260);
  expect(await textarea.evaluate((node) => getComputedStyle(node).maskImage)).not.toBe('none');
});

test('test_10a_the_stage_input_grows_upward_and_keeps_its_bottom_edge', async ({ page }) => {
  await startConcept(page);
  const composer = stageComposer(page);
  await expect(composer).toBeVisible();
  const textarea = composer.locator('textarea');
  await expect(textarea).toBeEnabled();

  const before = await composer.boundingBox();
  expect(before).not.toBeNull();
  if (before === null) return;

  await textarea.fill(lines(11));
  await expect
    .poll(async () => Math.round((await textarea.boundingBox())?.height ?? 0))
    .toBe(260);

  const after = await composer.boundingBox();
  expect(after).not.toBeNull();
  if (after === null) return;
  expect(after.y).toBeLessThan(before.y);
  expect(Math.abs(after.y + after.height - (before.y + before.height))).toBeLessThanOrEqual(2);
});

test('test_10a_send_and_plus_keep_a_44px_target_and_chips_stay_36px', async ({ page }) => {
  const composer = await openFirst(page);
  const plus = composer.locator('[data-slot="composer-plus"]');
  const send = composer.locator('[data-slot="composer-send"]');
  const visual = composer.locator('[data-slot="composer-send-visual"]');

  for (const target of [plus, send]) {
    const box = await target.boundingBox();
    expect(box).not.toBeNull();
    expect(Math.round(box?.width ?? 0)).toBe(44);
    expect(Math.round(box?.height ?? 0)).toBe(44);
  }
  const visualBox = await visual.boundingBox();
  expect(Math.round(visualBox?.width ?? 0)).toBe(32);
  expect(Math.round(visualBox?.height ?? 0)).toBe(32);

  await composer
    .locator('input[type="file"][data-kind="text"]')
    .setInputFiles([filePayload('notes.md', 'text/markdown', '원두는 신선도가 중요하다.')]);
  const attachment = composer.locator('[data-slot="composer-attachment"]');
  await expect(attachment).toBeVisible();
  expect(Math.round((await attachment.boundingBox())?.height ?? 0)).toBe(36);

  for (const kind of ['language', 'duration']) {
    const chip = composer.locator(`[data-slot="composer-action"][data-kind="${kind}"]`);
    const box = await chip.boundingBox();
    expect(box).not.toBeNull();
    expect(Math.round(box?.height ?? 0)).toBe(36);
  }

  const sendBox = await send.boundingBox();
  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  if (sendBox === null || viewport === null) return;
  expect(sendBox.x).toBeGreaterThanOrEqual(0);
  expect(sendBox.x + sendBox.width).toBeLessThanOrEqual(viewport.width + 0.5);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
});

test('test_10a_the_plus_menu_has_five_items_and_a_named_image_gap', async ({ page }) => {
  const composer = await openFirst(page);
  await composer.getByRole('button', { name: '파일이나 링크 더하기' }).press('Enter');

  const menu = page.getByRole('menu', { name: '더하기 메뉴' });
  await expect(menu).toBeVisible();
  await expect(menu.getByRole('menuitem')).toHaveCount(5);

  const link = menu.getByRole('menuitem', { name: '영상 링크 붙여넣기' });
  expect(await link.getAttribute('aria-disabled')).toBeNull();

  const image = menu.getByRole('menuitem', { name: /이미지 올리기/ });
  await expect(image).toHaveAttribute('aria-disabled', 'true');
  await expect(image).toContainText('곧 지원');
  const reason = page.getByRole('tooltip').filter({ hasText: '이미지 입력' });
  for (const item of [
    menu.getByRole('menuitem').first(),
    link,
    menu.getByRole('menuitem', { name: 'BGM 올리기' }),
    image,
  ]) {
    await page.keyboard.press('Tab');
    await expect(item).toBeFocused();
  }
  await expect(reason).toBeVisible();

  await page.keyboard.press('Tab');
  await expect(image).not.toBeFocused();
  await expect(reason).toBeHidden();
  await image.hover();
  await expect(reason).toBeVisible();

  const box = await menu.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  if (box === null || viewport === null) return;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 0.5);
});

test('test_10a_a_local_link_shows_the_warning_and_needs_consent', async ({ page }) => {
  const composer = await openFirst(page);
  await composer.getByRole('button', { name: '파일이나 링크 더하기' }).click();
  await page.getByRole('menuitem', { name: '영상 링크 붙여넣기' }).click();

  await expect(composer).toContainText('플랫폼 약관과 저작권');
  const attach = composer.getByRole('button', { name: '링크 첨부' });
  await expect(attach).toBeDisabled();

  await composer.getByRole('textbox', { name: '참고 영상 링크' }).fill('https://www.youtube.com/watch?v=abc123');
  await expect(attach).toBeDisabled();
  await expect(composer.locator('[data-slot="composer-attachment"]')).toHaveCount(0);

  await composer.getByRole('checkbox', { name: /동의해요/ }).check();
  await expect(attach).toBeEnabled();
  await attach.click();

  const attachment = composer.locator('[data-slot="composer-attachment"]');
  await expect(attachment).toHaveCount(1);
  await expect(attachment).toContainText('youtube.com');
  await expect(attachment).toContainText('받는 중');
});

test('test_10a_dragging_turns_the_box_into_a_rounded_dotted_field', async ({ page }) => {
  const composer = await openFirst(page);
  const dataTransfer = await page.evaluateHandle(() => {
    const transfer = new DataTransfer();
    transfer.items.add(new File(['원두는 신선도가 중요하다.'], 'notes.md', { type: 'text/markdown' }));
    transfer.items.add(new File(['첫 문장을 짧게.'], 'brief.txt', { type: 'text/plain' }));
    return transfer;
  });

  await composer.dispatchEvent('dragover', { dataTransfer });
  await expect(composer).toHaveAttribute('data-dragging', 'true');
  const surface = await composer.evaluate((node) => {
    const computed = getComputedStyle(node);
    return { style: computed.borderStyle, radius: computed.borderRadius };
  });
  expect(surface.style).toBe('dashed');
  expect(surface.radius).toBe('24px');

  await composer.dispatchEvent('drop', { dataTransfer });
  await expect(composer).not.toHaveAttribute('data-dragging', 'true');
  const attachments = composer.locator('[data-slot="composer-attachment"]');
  await expect(attachments).toHaveCount(2);
  await expect(composer.getByText('notes.md').first()).toBeVisible();
  await expect(composer.getByText('brief.txt').first()).toBeVisible();

  const remove = composer.getByRole('button', { name: 'notes.md 삭제' });
  await remove.focus();
  await page.keyboard.press('Enter');
  await expect(composer.getByText('notes.md')).toHaveCount(0);
  await expect(composer.getByText('brief.txt').first()).toBeVisible();
});

test('test_10a_six_files_show_the_limit_and_keep_five', async ({ page }) => {
  const composer = await openFirst(page);
  await composer
    .locator('input[type="file"][data-kind="text"]')
    .setInputFiles(
      Array.from({ length: 6 }, (_, index) =>
        filePayload(`note-${index + 1}.md`, 'text/markdown', `자료 ${index + 1}`),
      ),
    );

  await expect(composer.locator('[data-slot="composer-attachment"]')).toHaveCount(5);
  await expect(composer.getByRole('alert')).toContainText('최대 5개');
});

test('test_10a_bgm_files_keep_their_kind_and_all_selected_items', async ({ page }) => {
  const composer = await openFirst(page);
  await composer
    .locator('input[type="file"][data-kind="bgm"]')
    .setInputFiles([
      filePayload('theme.wav', 'audio/wav', 'RIFF'),
      filePayload('second.wav', 'audio/wav', 'RIFF'),
    ]);

  const chips = composer.locator('[data-slot="composer-attachment"][data-kind="bgm"]');
  await expect(chips).toHaveCount(2);
  await expect(composer.getByText('theme.wav').first()).toBeVisible();
  await expect(composer.getByText('second.wav').first()).toBeVisible();
  await expect(chips.first()).toContainText('BGM');
});

/**
 * The first screen is centred, so the cards and recent projects arriving below
 * the input move it. Reading the four boxes in one pass keeps them on one
 * frame; separate reads could straddle the move and report a row as tall as it.
 */
async function buttonRowHeight(composer: Locator): Promise<number> {
  return composer.evaluate((root) => {
    // The first screen carries the two picks; the concept rail's box carries plus and send only.
    const always = ['[data-slot="composer-plus"]', '[data-slot="composer-send"]'];
    if (always.some((selector) => root.querySelector(selector) === null)) {
      throw new Error('a button row part is missing');
    }
    const parts = [
      ...always,
      '[data-slot="composer-action"][data-kind="language"]',
      '[data-slot="composer-action"][data-kind="duration"]',
    ]
      .map((selector) => root.querySelector(selector))
      .filter((part) => part !== null);
    const boxes = parts.map((part) => (part as Element).getBoundingClientRect());
    return Math.max(...boxes.map((box) => box.bottom)) - Math.min(...boxes.map((box) => box.top));
  });
}

test('test_10a_the_button_row_stays_on_one_line_so_the_box_keeps_its_height', async ({ page }) => {
  const first = await openFirst(page);
  // Wrapping the send button onto a second line would make this about 94.
  expect(await buttonRowHeight(first)).toBeLessThanOrEqual(44);

  await startConcept(page);
  const stage = stageComposer(page);
  await expect(stage).toBeVisible();
  expect(await buttonRowHeight(stage)).toBeLessThanOrEqual(44);
});
