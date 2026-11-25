import { expect, test, type Locator, type Page } from '@playwright/test';

const SCENE_CARD = '[data-slot="scene-column"] [data-slot="scene-card"]';
const EXPORT_STAGE = '[data-slot="stage-panel"][data-stage="export"]';
const TOP_SAVE = '[data-slot="top-bar"] [data-slot="next-action"]';

/** Opens a step from the phone menu or the desktop tabs; export opens from the edit step's make action. */
async function openStage(page: Page, label: string): Promise<void> {
  const menu = page.getByRole('button', { name: '단계 열기' });
  if (await menu.isVisible()) {
    await menu.click();
    await page.getByRole('menuitem', { name: label, exact: true }).click();
  } else if (label === '내보내기') {
    await page.locator(TOP_SAVE).click();
    await page.getByRole('dialog', { name: '장면 확인' }).getByRole('button', { name: '영상 만들기' }).click();
  } else {
    await page
      .locator('[data-slot="stage-indicator"]')
      .getByRole('button', { name: label, exact: true })
      .click();
  }
}

async function openEdit(page: Page): Promise<void> {
  await page.goto('/');
  await page
    .getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })
    .fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByRole('heading', { name: '컨셉' })).toBeVisible();
  await openStage(page, '편집');
  await expect(page.locator(SCENE_CARD)).toHaveCount(5);
}

/** Starts the video from the edit step and waits for the result card. */
async function makeVideo(page: Page): Promise<Locator> {
  await openEdit(page);
  await page.locator('[data-slot="next-action"]').click();
  await page
    .getByRole('dialog', { name: '장면 확인' })
    .getByRole('button', { name: '영상 만들기' })
    .click();
  // The check finds nothing in the mock's own material-free video, so the making starts by itself.
  const card = page.getByRole('dialog', { name: '영상을 다 만들었어요', exact: true });
  await expect(card).toBeVisible({ timeout: 20_000 });
  return card;
}

async function closeCard(card: Locator): Promise<void> {
  await card.getByRole('button', { name: '결과 카드 닫기' }).click();
  await expect(card).toBeHidden();
}

/** The card closes onto the edit screen, so a test that needs the result panel opens the stage again. */
async function openExport(page: Page): Promise<void> {
  await openStage(page, '내보내기');
  await expect(page.locator(EXPORT_STAGE)).toBeVisible();
}

/** The screen is checked at both desktop widths, whichever project runs the file. */
function eachWidth(name: string, body: (page: Page) => Promise<void>): void {
  for (const [width, height] of [
    [1280, 800],
    [1920, 1080],
  ] as const) {
    test(`${name}_at_${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await body(page);
    });
  }
}

eachWidth('test_10a_the_edit_step_stays_usable_while_the_video_is_made_and_the_card_comes_after', async (page) => {
  await openEdit(page);
  await page.locator('[data-slot="next-action"]').click();
  await page
    .getByRole('dialog', { name: '장면 확인' })
    .getByRole('button', { name: '영상 만들기' })
    .click();
  // One confirm starts the making: the top bar carries the progress and no second press is asked.
  await expect(page.locator('.top-bar-status__trigger')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('[data-slot="export-start"]')).toHaveCount(0);
  await expect(page.getByRole('dialog', { name: '영상을 다 만들었어요', exact: true })).toHaveCount(0);

  const third = page.locator(SCENE_CARD).nth(2);
  await third.locator('button.card').click();
  await expect(third.locator('[data-slot="scene-selected"]')).toBeVisible();
  await expect(page.locator(EXPORT_STAGE)).toHaveCount(0);

  await expect(page.getByRole('dialog', { name: '영상을 다 만들었어요', exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(EXPORT_STAGE)).toBeVisible();
  await expect(page.locator('.top-bar-status__trigger')).toHaveCount(0);
  await expect(page.getByRole('progressbar')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /멈추기|취소/u })).toHaveCount(0);
});

eachWidth('test_10a_the_result_card_is_814_wide_and_stacks_the_facts_from_the_top', async (page) => {
  const card = await makeVideo(page);
  await page.waitForTimeout(300);

  const box = await card.boundingBox();
  expect(box).not.toBeNull();
  if (box === null) return;
  expect(Math.round(box.width)).toBe(814);

  await expect(card.getByRole('heading', { name: '영상을 다 만들었어요', exact: true })).toBeVisible();
  const names = await card.getByRole('button').evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute('aria-label') ?? node.textContent ?? ''),
  );
  for (const forbidden of ['닫기', '크게 보기', '이 영상으로 새 영상 만들기']) {
    expect(names).not.toContain(forbidden);
  }
  expect(names).toContain('결과 카드 닫기');

  const labels = await card.locator('dt').allTextContents();
  expect(labels).toEqual(['길이', '형식', '자막', '사용량']);

  const geometry = await card.evaluate((node) => {
    const rect = (selector: string) => node.querySelector(selector)?.getBoundingClientRect();
    const side = rect('.export-result__side');
    const description = rect('.export-result__description');
    const facts = rect('.export-facts');
    const actions = rect('.export-result__actions');
    const rows = Array.from(node.querySelectorAll('.export-facts dt')).map((term) => term.getBoundingClientRect().top);
    return {
      sideBottom: side?.bottom ?? 0,
      descriptionBottom: description?.bottom ?? 0,
      factsTop: facts?.top ?? 0,
      factsBottom: facts?.bottom ?? 0,
      actionsTop: actions?.top ?? 0,
      actionsBottom: actions?.bottom ?? 0,
      rows,
    };
  });
  // The facts follow the one-line description; only the button row sits at the bottom.
  expect(geometry.factsTop - geometry.descriptionBottom).toBeLessThanOrEqual(35);
  expect(geometry.rows).toEqual([...geometry.rows].sort((left, right) => left - right));
  expect(Math.round(geometry.actionsBottom)).toBe(Math.round(geometry.sideBottom));
  expect(geometry.actionsTop).toBeGreaterThanOrEqual(geometry.factsBottom);

  const actions = card.locator('.export-result__actions button');
  await expect(actions).toHaveText(['편집으로', 'mp4 저장']);
});

eachWidth('test_10a_the_card_x_keeps_its_focus_ring_inside_the_card', async (page) => {
  const card = await makeVideo(page);
  await page.waitForTimeout(300);

  const close = card.getByRole('button', { name: '결과 카드 닫기' });
  for (let press = 0; press < 12; press += 1) {
    await page.keyboard.press('Tab');
    if (await close.evaluate((node) => node === document.activeElement)) break;
  }
  await expect(close).toBeFocused();

  const ring = await close.evaluate((node) => {
    const style = getComputedStyle(node);
    const scroll = node.closest('.dialog__scroll')?.getBoundingClientRect();
    const own = node.getBoundingClientRect();
    return {
      style: style.outlineStyle,
      reach: Math.max(0, parseFloat(style.outlineOffset) + parseFloat(style.outlineWidth)),
      right: own.right,
      top: own.top,
      scrollRight: scroll?.right ?? 0,
      scrollTop: scroll?.top ?? 0,
    };
  });
  expect(ring.style).not.toBe('none');
  expect(ring.right + ring.reach).toBeLessThanOrEqual(ring.scrollRight + 0.5);
  expect(ring.top - ring.reach).toBeGreaterThanOrEqual(ring.scrollTop - 0.5);
});

eachWidth('test_10a_closing_the_card_lands_on_the_edit_step_with_the_finished_video', async (page) => {
  const card = await makeVideo(page);
  await closeCard(card);

  await expect(page.locator('[data-slot="stage-panel"][data-stage="edit"]')).toBeVisible();
  await expect(page.locator(EXPORT_STAGE)).toHaveCount(0);
  await expect(page.locator('.edit-preview-area')).toBeVisible();
});

eachWidth('test_10a_the_top_bar_save_is_a_named_primary_button_44_high_in_the_top_right', async (page) => {
  const card = await makeVideo(page);
  await closeCard(card);
  await openExport(page);

  const save = page.locator(TOP_SAVE);
  await expect(save).toHaveText('mp4 저장');
  await expect(save).toBeEnabled();
  const box = await save.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  if (box === null || viewport === null) return;
  expect(Math.round(box.height)).toBe(44);
  expect(box.x + box.width).toBeGreaterThan(viewport.width - 40);
  expect(box.y + box.height).toBeLessThan(100);
  await expect(save).toHaveClass(/button--primary/u);
});

eachWidth('test_29_the_caption_button_says_srt_only_in_its_tooltip', async (page) => {
  const card = await makeVideo(page);
  await closeCard(card);
  await openExport(page);

  const caption = page.locator('[data-slot="top-bar"]').getByRole('button', { name: '자막 저장' });
  await expect(caption).toBeVisible();
  await expect(page.locator('body')).not.toContainText('SRT');
  await caption.hover();
  await expect(page.getByRole('tooltip')).toHaveText('SRT 파일로 저장해요');
});

eachWidth('test_10a_the_result_scenes_use_the_24_number_circle_and_a_press_sets_the_target', async (page) => {
  const card = await makeVideo(page);
  await closeCard(card);
  await openExport(page);

  const rail = page.locator('[data-slot="export-scenes"]');
  await expect(rail.locator('[data-slot="result-scene"]')).toHaveCount(5);
  const number = await rail.locator('.card__number').first().boundingBox();
  expect(number).not.toBeNull();
  if (number === null) return;
  expect(Math.round(number.width)).toBe(24);
  expect(Math.round(number.height)).toBe(24);

  await rail.locator('[data-slot="result-scene"] button').nth(2).click();
  await expect(page.locator(EXPORT_STAGE)).toBeVisible();
  await expect(page.getByRole('button', { name: '대상 지우기' })).toBeVisible();
  await expect(page.locator('[data-slot="conversation"]').getByText('장면 3', { exact: true }).first()).toBeVisible();
  const composer = page.locator('[data-slot="conversation"] [data-slot="composer"]');
  await composer.locator('textarea').fill('이 장면만 줄여 줘');
  await composer.getByRole('button', { name: '보내기' }).click();
  await expect(page.locator('[data-slot="edit-chat"]')).toContainText('이 장면만 줄여 줘');
  await expect(page.locator(EXPORT_STAGE)).toBeVisible();
});

eachWidth('test_23_the_result_screen_fits_the_width_without_a_sideways_scroll', async (page) => {
  const card = await makeVideo(page);
  await closeCard(card);
  await openExport(page);

  const overflow = await page.evaluate(() => {
    const stage = document.querySelector<HTMLElement>('[data-slot="stage-scroll"]');
    return {
      page: document.documentElement.scrollWidth - window.innerWidth,
      stage: stage === null ? 0 : stage.scrollWidth - stage.clientWidth,
    };
  });
  expect(overflow.page).toBeLessThanOrEqual(0);
  expect(overflow.stage).toBeLessThanOrEqual(0);
  await expect(page.locator('[data-slot="export-panel"]')).toBeVisible();
  await expect(page.locator('[data-slot="export-usage"]')).toBeVisible();
});
