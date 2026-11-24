import { readFileSync } from 'node:fs';

import { expect, test, type Locator, type Page } from '@playwright/test';

import { CARD_DESCRIPTION_LIMIT, CARD_TITLE_LIMIT } from '../../src/features/concept/cards';
import { capture } from '../support/capture';

async function start(page: Page): Promise<Locator> {
  await page.goto('/');
  await page.getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' }).fill('별이 보이는 이유');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  const concept = page.locator('[data-slot="concept-screen"]');
  await expect(concept.getByRole('heading', { name: '컨셉', exact: true })).toBeVisible();
  await expect(concept.getByRole('heading', { name: '이야기 방식', exact: true })).toBeVisible();
  await expect(concept.getByRole('button', { name: '딱 3가지만', exact: true })).toBeVisible();
  // A narrow viewport shows two card rows; the tests need every story card.
  const more = concept.getByRole('button', { name: '더 보기', exact: true });
  if (await more.isVisible()) await more.click();
  return concept;
}

async function move(page: Page, name: string): Promise<void> {
  const menu = page.getByRole('button', { name: '단계 열기' });
  if (await menu.isVisible()) {
    await menu.click();
    await page.getByRole('menuitem', { name, exact: true }).click();
  } else {
    await page.getByRole('navigation', { name: '단계' }).getByRole('button', { name, exact: true }).click();
  }
}

function composer(page: Page): Locator {
  const width = page.viewportSize()?.width ?? 0;
  return page.locator(width < 768 ? '[data-slot="composer-dock"]' : '[data-slot="conversation"]');
}

async function applyIfNeeded(concept: Locator): Promise<void> {
  const apply = concept.getByRole('button', { name: '적용', exact: true });
  if (await apply.isVisible()) await apply.click();
}

async function openTune(concept: Locator, title: string): Promise<Locator> {
  await concept.getByRole('button', { name: `${title} 세부 조정`, exact: true }).click();
  const panel = concept.getByRole('region', { name: `${title} 세부 조정`, exact: true });
  await expect(panel).toBeVisible();
  return panel;
}

test('test_3_cards_show_origins_and_locks', async ({ page }) => {
  const concept = await start(page);
  const tune = await openTune(concept, '만약 ~라면?');
  const register = tune.getByRole('combobox', { name: '말투', exact: true });
  await register.selectOption({ label: '설명체' });
  await applyIfNeeded(concept);
  await expect(register.locator('option:checked')).toHaveText('설명체');
  await concept.getByText('세부 설정', { exact: true }).click();
  const row = concept.locator('[data-field="/format/register"]');
  await expect(row.getByText('직접', { exact: true })).toBeVisible();
  await row.getByRole('button', { name: /말투: 변화/ }).click();
  await applyIfNeeded(concept);
  await expect(row.getByRole('button', { name: /말투: 고정/ })).toHaveAttribute('aria-pressed', 'true');
});

test('test_4_invalid_combinations_block', async ({ page }) => {
  const concept = await start(page);
  await concept.getByText('세부 설정', { exact: true }).click();
  await concept.getByRole('combobox', { name: '자막 방식', exact: true }).selectOption({ label: '대화창 타자' });
  await expect(concept.getByRole('alert')).toBeVisible();
  await expect(concept.getByRole('combobox', { name: '자막 방식', exact: true }).locator('option:checked')).not.toHaveText('대화창 타자');
});

test('test_4_fine_tune_panel_attached_to_selected_card_and_values_stay_separate', async ({ page }) => {
  const concept = await start(page);
  const itsLike = concept.getByRole('button', { name: '○○로 치면', exact: true });
  const whatIf = concept.getByRole('button', { name: '만약 ~라면?', exact: true });
  const panel = await openTune(concept, '○○로 치면');
  const rowBox = await concept.locator('.concept-card-grid').first().boundingBox();
  const cardBox = await concept.locator('.concept-card-slot', { has: itsLike }).boundingBox();
  const panelBox = await panel.boundingBox();
  expect(rowBox).not.toBeNull();
  expect(cardBox).not.toBeNull();
  expect(panelBox).not.toBeNull();
  expect(Math.abs(panelBox!.x - rowBox!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(panelBox!.width - rowBox!.width)).toBeLessThanOrEqual(1);
  // The board hangs 6 below the selected card's face.
  expect(Math.round(panelBox!.y - (cardBox!.y + cardBox!.height))).toBe(6);

  const humor = panel.getByRole('combobox', { name: '유머', exact: true });
  await humor.selectOption({ label: '없음' });
  await applyIfNeeded(concept);
  await expect(humor.locator('option:checked')).toHaveText('없음');

  await whatIf.click();
  const switched = concept.getByRole('region', { name: '만약 ~라면? 세부 조정', exact: true });
  await expect(switched.getByRole('combobox', { name: '유머', exact: true }).locator('option:checked')).toHaveText('가볍게');

  await move(page, '편집');
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();
  await move(page, '컨셉');
  const back = await openTune(concept, '○○로 치면');
  await expect(back.getByRole('combobox', { name: '유머', exact: true }).locator('option:checked')).toHaveText('없음');

  await concept.getByRole('button', { name: '딱 3가지만', exact: true }).click();
  const first = concept.getByRole('region', { name: '딱 3가지만 세부 조정', exact: true });
  await expect(first.getByRole('combobox', { name: '유머', exact: true }).locator('option:checked')).toHaveText('없음');
});

test('test_4_every_fine_tune_panel_keeps_the_card_row_edges', async ({ page }) => {
  const concept = await start(page);
  const row = await concept.locator('.concept-card-grid').first().boundingBox();
  expect(row).not.toBeNull();
  for (const title of ['만약 ~라면?', '딱 3가지만', '○○로 치면']) {
    const panel = await openTune(concept, title);
    const box = await panel.boundingBox();
    expect(box).not.toBeNull();
    expect(Math.abs(box!.x - row!.x)).toBeLessThanOrEqual(1);
    expect(Math.abs(box!.width - row!.width)).toBeLessThanOrEqual(1);
    expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  }
});

test('test_5_terms_come_from_concept_json_without_old_terms', async ({ page }) => {
  const locale = JSON.parse(readFileSync(new URL('../../src/locales/ko/concept.json', import.meta.url), 'utf8')) as Record<string, string>;
  const serialized = JSON.stringify(locale);
  expect(serialized).not.toContain('이야기 틀');
  expect(serialized).not.toContain('화면 틀');
  expect(locale.story).toBe('이야기 방식');
  expect(locale['field.format.layout']).toBe('화면 구성');
  expect(locale['value.subject']).toBe('주인공');

  const concept = await start(page);
  await expect(concept.getByRole('heading', { name: locale.story, exact: true })).toBeVisible();
  await expect(concept.getByRole('heading', { name: locale.style, exact: true })).toBeVisible();
  await expect(concept.getByRole('heading', { name: locale.character, exact: true })).toBeVisible();
  const tune = await openTune(concept, '만약 ~라면?');
  await expect(tune.getByText(locale['field.format.layout'], { exact: true })).toBeVisible();
  const text = await concept.innerText();
  expect(text).not.toContain('이야기 틀');
  expect(text).not.toContain('화면 틀');
});

test('test_10a_the_character_preview_values_are_exposed_as_text', async ({ page }) => {
  const concept = await start(page);
  const preview = concept.locator('.concept-example');
  const values = await preview.locator('span').last().innerText();
  expect(await preview.ariaSnapshot()).toContain(values);
});

test('test_5_reference_band_sits_above_the_groups_and_opens_the_reference_screen', async ({ page }) => {
  const concept = await start(page);
  const band = concept.getByRole('button', { name: '참고 영상으로 채우기', exact: true });
  await expect(band).toHaveCount(1);
  const bandBox = await band.boundingBox();
  const headingBox = await concept.getByRole('heading', { name: '이야기 방식', exact: true }).boundingBox();
  expect(bandBox).not.toBeNull();
  expect(headingBox).not.toBeNull();
  expect(bandBox!.y + bandBox!.height).toBeLessThanOrEqual(headingBox!.y);
  await band.click();
  await expect(page.getByRole('dialog', { name: '참고 영상 분석', exact: true })).toBeVisible();
});

test('test_7_chat_values_survive_steps_and_confirmation', async ({ page }) => {
  let concept = await start(page);
  const input = composer(page);
  await input.getByRole('textbox').fill('농담 빼기');
  await input.getByRole('button', { name: '보내기', exact: true }).click();
  const tune = await openTune(concept, '딱 3가지만');
  await expect(tune.getByRole('combobox', { name: '유머', exact: true }).locator('option:checked')).toHaveText('없음');
  await move(page, '편집');
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();
  await expect(input.locator('[data-slot="composer-target"]')).toContainText('장면 1');
  await input.getByRole('button', { name: '대상 지우기', exact: true }).click();
  await input.getByRole('textbox').fill('설명체로');
  await input.getByRole('button', { name: '보내기', exact: true }).click();
  await input.getByRole('button', { name: '모두 적용', exact: true }).click();
  await move(page, '컨셉');
  concept = page.locator('[data-slot="concept-screen"]');
  await applyIfNeeded(concept);
  const back = await openTune(concept, '딱 3가지만');
  await expect(back.getByRole('combobox', { name: '말투', exact: true }).locator('option:checked')).toHaveText('설명체');
  await concept.getByRole('button', { name: '정하고 대본 만들기', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '이 컨셉으로 정할까요?' });
  await expect(dialog.getByRole('button', { name: '취소', exact: true })).toBeFocused();
  await dialog.getByRole('button', { name: '정하고 대본 만들기', exact: true }).click();
  await expect(concept.getByText('컨셉은 이 영상을 만들 때 정했어요.', { exact: true })).toBeVisible();
  await move(page, '편집');
  await move(page, '컨셉');
  const locked = await openTune(concept, '딱 3가지만');
  await expect(locked.getByRole('combobox', { name: '말투', exact: true })).toBeDisabled();
  await expect(locked.getByRole('combobox', { name: '말투', exact: true }).locator('option:checked')).toHaveText('설명체');
});

test('test_6_style_jobs_review_values_without_confirming_concept', async ({ page }) => {
  const concept = await start(page);
  await concept.getByRole('button', { name: '말로 만들기', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '말로 만들기' });
  await dialog.getByRole('textbox').fill('눈을 가늘게');
  await dialog.getByRole('button', { name: '작업 시작', exact: true }).click();
  const review = concept.getByRole('region', { name: '바뀌는 값과 영향' });
  await expect(review).toBeVisible();
  await expect(review).toContainText('그림체');
  await expect(review).toContainText('확정 상태는 바뀌지 않아요.');
  await review.getByRole('button', { name: '적용', exact: true }).click();
  await expect(review).toHaveCount(0);
  await expect(concept.getByRole('combobox', { name: '그림체', exact: true }).locator('option:checked')).not.toHaveText('픽셀');
  await expect(concept.getByRole('button', { name: '정하고 대본 만들기', exact: true })).toBeEnabled();
});

test('test_7_unsupported_requests_remain_visible_without_a_change', async ({ page }) => {
  const concept = await start(page);
  await composer(page).getByRole('textbox').fill('실제 사람 사진으로 춤추는 영상을 만들어 줘');
  await composer(page).getByRole('button', { name: '보내기', exact: true }).click();
  await expect(concept.getByText('처리하지 못한 내용', { exact: true })).toBeVisible();
});

test('test_4_cards_have_fixed_height_selection_and_no_outline', async ({ page }) => {
  const concept = await start(page);
  const selected = concept.getByRole('button', { name: '딱 3가지만', exact: true });
  const other = concept.getByRole('button', { name: '○○로 치면', exact: true });
  const selectedFace = concept.locator('.concept-card-slot', { has: selected });
  const otherFace = concept.locator('.concept-card-slot', { has: other });
  const box = await selectedFace.boundingBox();
  expect(box).not.toBeNull();
  expect(Math.round(box!.width)).toBe(216);
  expect(Math.round(box!.height)).toBe(266);
  const picture = await selected.locator('.concept-card__picture').boundingBox();
  expect(picture).not.toBeNull();
  expect(Math.round(picture!.width)).toBe(200);
  expect(Math.round(picture!.height)).toBe(150);
  const titleBox = await selected.locator('.concept-card__title').boundingBox();
  const descriptionBox = await selected.locator('.concept-card__description').boundingBox();
  expect(Math.round(titleBox!.height)).toBe(20);
  expect(Math.round(descriptionBox!.height)).toBe(18);
  expect(await selected.evaluate((node) => getComputedStyle(node).borderTopWidth)).toBe('0px');
  expect(await selectedFace.evaluate((node) => getComputedStyle(node).backgroundColor)).toBe('rgb(229, 232, 235)');
  expect(await otherFace.evaluate((node) => getComputedStyle(node).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
  expect(await selected.locator('.concept-card__title').evaluate((node) => getComputedStyle(node).fontWeight)).toBe('700');
  expect(await other.locator('.concept-card__title').evaluate((node) => getComputedStyle(node).fontWeight)).toBe('400');
  await expect(selected).toHaveAttribute('title', '딱 3가지만');
  expect(await selected.locator('svg.lucide-check').count()).toBe(0);
  const title = await other.locator('.concept-card__title').innerText();
  const description = await other.locator('.concept-card__description').innerText();
  expect(Array.from(title).length).toBeLessThanOrEqual(CARD_TITLE_LIMIT);
  expect(Array.from(description).length).toBeLessThanOrEqual(CARD_DESCRIPTION_LIMIT);
});

test('test_5_concept_and_reference_documents_use_the_scroll_pane', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  const concept = await start(page);
  const viewport = concept.locator('.scroll-pane__viewport');
  expect(await viewport.evaluate((node) => getComputedStyle(node).scrollbarWidth)).toBe('none');
  const jump = concept.getByRole('button', { name: '아래로 넘기기', exact: true });
  await expect(jump).toBeVisible();
  const before = await viewport.evaluate((node) => node.scrollTop);
  await jump.click();
  await expect.poll(() => viewport.evaluate((node) => node.scrollTop)).toBeGreaterThan(before);

  await concept.getByRole('button', { name: '참고 영상으로 채우기', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '참고 영상 분석', exact: true });
  await expect(dialog).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 360 });
  const dialogViewport = dialog.locator('.scroll-pane__viewport');
  expect(await dialogViewport.evaluate((node) => getComputedStyle(node).scrollbarWidth)).toBe('none');
  await expect(dialog.getByRole('button', { name: '아래로 넘기기', exact: true })).toBeVisible();
});

test('test_23_keyboard_cards_and_docked_action_have_no_horizontal_overflow', async ({ page }) => {
  const concept = await start(page);
  const card = concept.getByRole('button', { name: '만약 ~라면?', exact: true });
  await card.focus();
  await page.keyboard.press('Enter');
  await applyIfNeeded(concept);
  await expect(card).toHaveAttribute('aria-pressed', 'true');
  const action = concept.getByRole('button', { name: '정하고 대본 만들기', exact: true });
  const box = await action.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await expect(page.locator('[data-slot="top-bar"] [data-slot="next-action"]')).toBeHidden();
});

test('test_23_captures_synthetic_concept_at_each_supported_width', async ({ page }, testInfo) => {
  // The capture writes one file per width; mobile is out of MVP scope and
  // WebKit would overwrite the Chromium pixels with a different rendering.
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Desktop Chromium captures only.');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const [width, height] of [[1280, 800], [1920, 1080]] as const) {
    await page.setViewportSize({ width, height });
    const concept = await start(page);
    await expect(concept.getByRole('button', { name: '아래로 넘기기', exact: true })).toBeVisible();
    await capture(page, testInfo, `tests/concept/screens/concept-${width}.png`);
    const tune = await openTune(concept, '만약 ~라면?');
    await tune.scrollIntoViewIfNeeded();
    await capture(page, testInfo, `tests/concept/screens/concept-tune-${width}.png`);
  }
});
