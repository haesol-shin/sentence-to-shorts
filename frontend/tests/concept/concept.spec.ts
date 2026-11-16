import { expect, test, type Locator, type Page } from '@playwright/test';

import { capture } from '../support/capture';

async function start(page: Page): Promise<Locator> {
  await page.goto('/');
  await page.getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' }).fill('별이 보이는 이유');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  const concept = page.locator('[data-slot="concept-screen"]');
  await expect(concept.getByRole('heading', { name: '컨셉', exact: true })).toBeVisible();
  await expect(concept.getByRole('combobox', { name: '말투', exact: true })).toBeEnabled();
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
  const apply = concept.getByRole('button', { name: '변경 적용', exact: true });
  if (await apply.isVisible()) await apply.click();
}

test('test_3_cards_preserve_direct_values_and_show_origins_and_locks', async ({ page }) => {
  const concept = await start(page);
  const register = concept.getByRole('combobox', { name: '말투', exact: true });
  await register.selectOption({ label: '설명체' });
  await applyIfNeeded(concept);
  await concept.getByRole('button', { name: /만약 ~라면\?/ }).click();
  await applyIfNeeded(concept);
  await expect(register.locator('option:checked')).toHaveText('설명체');
  const row = concept.locator('[data-field="/format/register"]');
  await expect(row.getByText('직접', { exact: true })).toBeVisible();
  await row.getByRole('button', { name: /말투: 변화/ }).click();
  await applyIfNeeded(concept);
  await expect(row.getByRole('button', { name: /말투: 고정/ })).toHaveAttribute('aria-pressed', 'true');
});

test('test_4_invalid_combinations_block_and_role_reset_restores_parts', async ({ page }) => {
  const concept = await start(page);
  await concept.getByText('세부 설정', { exact: true }).click();
  await concept.getByRole('combobox', { name: '자막 방식', exact: true }).selectOption({ label: '대화창 타자' });
  await expect(concept.getByRole('alert')).toBeVisible();
  await expect(concept.getByRole('combobox', { name: '자막 방식', exact: true }).locator('option:checked')).not.toHaveText('대화창 타자');
  const role = concept.getByRole('combobox', { name: '캐릭터 역할', exact: true });
  await role.selectOption({ label: '없음' });
  await applyIfNeeded(concept);
  await concept.getByRole('button', { name: '캐릭터 역할: 기본값으로', exact: true }).click();
  await applyIfNeeded(concept);
  await expect(role.locator('option:checked')).toHaveText('진행자');
  await expect(concept.getByRole('combobox', { name: '몸', exact: true }).locator('option:checked')).not.toHaveText('없음');
});

test('test_7_chat_values_survive_cards_steps_and_confirmation', async ({ page }) => {
  let concept = await start(page);
  const input = composer(page);
  await input.getByRole('textbox').fill('농담 빼기');
  await input.getByRole('button', { name: '보내기', exact: true }).click();
  await expect(concept.getByRole('combobox', { name: '유머', exact: true }).locator('option:checked')).toHaveText('없음');
  await concept.getByRole('button', { name: /○○로 치면/ }).click();
  await applyIfNeeded(concept);
  await expect(concept.getByRole('combobox', { name: '유머', exact: true }).locator('option:checked')).toHaveText('없음');
  await move(page, '편집');
  await expect(page.locator('[data-slot="edit-stage"]')).toBeVisible();
  await input.getByRole('textbox').fill('설명체로');
  await input.getByRole('button', { name: '보내기', exact: true }).click();
  await move(page, '컨셉');
  concept = page.locator('[data-slot="concept-screen"]');
  await applyIfNeeded(concept);
  await expect(concept.getByRole('combobox', { name: '말투', exact: true }).locator('option:checked')).toHaveText('설명체');
  await concept.getByRole('button', { name: '정하고 대본 만들기', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '이 컨셉으로 정할까요?' });
  await expect(dialog.getByRole('button', { name: '취소', exact: true })).toBeFocused();
  await dialog.getByRole('button', { name: '정하고 대본 만들기', exact: true }).click();
  await expect(concept.getByText('컨셉은 이 영상을 만들 때 정했어요.', { exact: true })).toBeVisible();
  await move(page, '편집');
  await move(page, '컨셉');
  await expect(concept.getByRole('combobox', { name: '말투', exact: true })).toBeDisabled();
  await expect(concept.getByRole('combobox', { name: '말투', exact: true }).locator('option:checked')).toHaveText('설명체');
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
  await review.getByRole('button', { name: '변경 적용', exact: true }).click();
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

test('test_23_keyboard_cards_and_docked_action_have_no_horizontal_overflow', async ({ page }) => {
  const concept = await start(page);
  const card = concept.getByRole('button', { name: /만약 ~라면\?/ });
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
  await start(page);
  const width = page.viewportSize()!.width;
  await capture(page, testInfo, `tests/concept/screens/concept-${width}.png`, true);
});
