import { expect, test, type Page } from '@playwright/test';

/** Opens a step through the phone menu, or the step tabs on a desktop. */
async function openStage(page: Page, label: string): Promise<void> {
  const menu = page.getByRole('button', { name: '단계 열기' });
  if (await menu.isVisible()) {
    await menu.click();
    await page.getByRole('menuitem', { name: label }).click();
    return;
  }
  await page.locator('[data-slot="stage-indicator"]').getByRole('button', { name: label }).click();
}

async function openEdit(page: Page): Promise<void> {
  await page.getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' }).fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();

  await openStage(page, '편집');
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();
}

test('test_10a_the_step_tabs_show_three_steps_on_every_stage_screen', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-slot="stage-indicator"]')).toHaveCount(0);

  await page.getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' }).fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();

  const indicator = page.locator('[data-slot="stage-indicator"]');
  await expect(indicator).toBeVisible();
  await expect(page.getByRole('button', { name: '단계 열기' })).toBeHidden();
  await expect(indicator.getByRole('button')).toHaveText(['컨셉', '대본', '편집']);
  await expect(indicator.locator('[aria-current="step"]')).toHaveText('컨셉');

  await indicator.getByRole('button', { name: '편집' }).click();
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();
  await expect(indicator.locator('[aria-current="step"]')).toHaveText('편집');

  await indicator.getByRole('button', { name: '대본' }).click();
  await expect(page.locator('[data-slot="stage-panel"][data-stage="script"]')).toBeVisible();
  await expect(indicator.locator('[aria-current="step"]')).toHaveText('대본');
});

test('test_10a_the_edit_screen_puts_the_conversation_left_of_the_frames', async ({ page }) => {
  await page.goto('/');
  await openEdit(page);

  const width = page.viewportSize()?.width ?? 0;
  test.skip(width !== 1920, 'the desktop edit layout is measured at 1920px');

  const conversation = await page.locator('[data-slot="conversation"]').boundingBox();
  const frames = await page.locator('[data-slot="scene-column"]').boundingBox();
  const preview = await page.locator('[data-slot="preview"]').boundingBox();
  const panel = await page.locator('[data-slot="stage-panel"]').boundingBox();
  expect(conversation).not.toBeNull();
  expect(frames).not.toBeNull();
  expect(preview).not.toBeNull();
  expect(panel).not.toBeNull();
  if (conversation === null || frames === null || preview === null || panel === null) return;

  expect(conversation.x + conversation.width).toBeLessThanOrEqual(frames.x + 1);
  expect(frames.x + frames.width).toBeLessThanOrEqual(preview.x + 1);
  expect(preview.x + preview.width).toBeLessThanOrEqual(panel.x + 1);

  const frameColour = await page
    .locator('[data-slot="scene-column"]')
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  expect(frameColour).toBe('rgb(242, 244, 246)');
});

test('test_10a_the_preview_keeps_its_nine_by_sixteen_frame', async ({ page }) => {
  await page.goto('/');
  await openEdit(page);

  const frame = page.locator('.video-preview').first();
  const box = await frame.boundingBox();
  expect(box).not.toBeNull();
  if (box === null) return;

  expect(box.height / box.width).toBeGreaterThan(1.7);
  expect(box.height / box.width).toBeLessThan(1.85);
  expect(await frame.evaluate((node) => getComputedStyle(node).borderTopLeftRadius)).toBe('12px');
});

test('test_10a_the_next_action_keeps_its_seat_at_the_top_right', async ({ page }) => {
  await page.goto('/');
  await openEdit(page);

  const action = page.locator('[data-slot="next-action"]');
  await expect(action).toBeVisible();
  await expect(action).toHaveAccessibleName('영상 만들기');

  const box = await action.boundingBox();
  const width = page.viewportSize()?.width ?? 0;
  expect(box).not.toBeNull();
  if (box === null) return;
  expect(box.x + box.width).toBeGreaterThan(width - 40);
  expect(box.y + box.height).toBeLessThan(100);
});

test('test_10a_the_next_action_stays_inside_the_screen_that_owns_it', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' }).fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();

  const width = page.viewportSize()?.width ?? 0;
  // The concept screen is already open, and export has no tab: it opens from the edit step.
  const walk: readonly (readonly [string, string | null])[] = [
    ['concept', null],
    ['script', '대본'],
    ['edit', '편집'],
    ['export', null],
  ];

  for (const [stage, label] of walk) {
    if (label !== null) {
      await openStage(page, label);
    } else if (stage === 'export') {
      await page.locator('[data-slot="next-action"]').click();
      await page.getByRole('dialog', { name: '장면 확인' }).getByRole('button', { name: '영상 만들기' }).click();
    }
    await expect(
      page.locator(stage === 'concept' ? '[data-slot="concept-screen"]' : '[data-slot="stage-panel"]'),
    ).toBeVisible();
    if (stage !== 'concept') {
      await expect(page.locator('[data-slot="stage-panel"]')).toHaveAttribute('data-stage', stage);
      if (stage === 'script') {
        // The script screen carries its step action in the document footer.
        await expect(page.locator('[data-slot="next-action"]')).toHaveCount(0);
        await expect(page.locator('[data-slot="script-next"]')).toBeVisible();
      } else {
        const box = await page.locator('[data-slot="next-action"]').boundingBox();
        expect(box).not.toBeNull();
        if (box === null) continue;
        expect(box.x).toBeGreaterThan(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
      }
    }

    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflows).toBe(false);
  }
});

test('test_23_the_phone_edit_screen_keeps_a_scene_row', async ({ page }) => {
  await page.goto('/');
  await openEdit(page);

  const strip = page.locator('[data-slot="scene-strip"]');
  const width = page.viewportSize()?.width ?? 0;
  if (width >= 768) {
    await expect(strip).toBeHidden();
    return;
  }

  await expect(strip).toBeVisible();
  expect(await strip.evaluate((node) => getComputedStyle(node).overflowX)).toBe('auto');
  await expect(strip.getByRole('button', { name: '장면 추가' })).toBeVisible();
});

test('test_23_scrolling_the_phone_stage_folds_the_preview', async ({ page }) => {
  const width = page.viewportSize()?.width ?? 0;
  test.skip(width >= 768, 'the folding preview belongs to the phone layout');

  // A short phone screen, so the stage really has room to scroll.
  await page.setViewportSize({ width, height: 360 });
  await page.goto('/');
  await openEdit(page);

  const preview = page.locator('[data-slot="preview"]');
  await expect(preview).not.toHaveAttribute('data-collapsed', 'true');

  const reached = await page.locator('[data-slot="stage-scroll"]').evaluate((node) => {
    node.scrollTop = 120;
    node.dispatchEvent(new Event('scroll'));
    return node.scrollTop;
  });
  expect(reached).toBeGreaterThan(24);

  await expect(preview).toHaveAttribute('data-collapsed', 'true');
});
