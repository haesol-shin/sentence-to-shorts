import { expect, test, type Locator, type Page } from '@playwright/test';

import { capture } from '../support/capture';

const WIDTHS = [
  { width: 1280, height: 800 },
  { width: 1920, height: 1080 },
] as const;

async function openScript(page: Page, size?: { width: number; height: number }): Promise<Locator> {
  if (size !== undefined) {
    await page.setViewportSize(size);
  }
  await page.goto('/');
  await page
    .getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })
    .fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  await expect(page.getByRole('heading', { name: '컨셉', exact: true })).toBeVisible();
  await openStage(page, '대본');
  const screen = page.locator('[data-slot="stage-panel"][data-stage="script"]');
  await expect(screen.getByRole('heading', { name: '대본', exact: true })).toBeVisible();
  return screen;
}

function sceneCards(screen: Locator): Locator {
  return screen.locator('[data-slot="script-scene"]');
}

function firstLine(card: Locator): Locator {
  return card.locator('[data-slot="script-line-input"]').first();
}

async function openStage(page: Page, label: string): Promise<void> {
  const menu = page.getByRole('button', { name: '단계 열기' });
  if (await menu.isVisible()) {
    await menu.click();
    await page.getByRole('menuitem', { name: label, exact: true }).click();
    return;
  }
  await page.locator('[data-slot="stage-indicator"]').getByRole('button', { name: label }).click();
}

test('test_10a_the_script_step_has_the_document_head_and_one_step_button', async ({ page }) => {
  const screen = await openScript(page);

  await expect(screen.getByRole('combobox', { name: '길이', exact: true })).toBeVisible();
  await expect(screen.getByRole('combobox', { name: '장면 수', exact: true })).toBeVisible();
  await expect(screen.getByRole('combobox', { name: '말투', exact: true })).toBeVisible();
  await expect(sceneCards(screen)).toHaveCount(5);

  const first = sceneCards(screen).first();
  await expect(first.getByRole('button', { name: '장면 1 순서 바꾸기', exact: true })).toBeVisible();
  await expect(first.getByRole('button', { name: '위로 옮기기', exact: true })).toBeDisabled();
  await expect(first.getByRole('button', { name: '아래로 옮기기', exact: true })).toBeEnabled();
  await expect(first.getByRole('button', { name: '장면 1 메뉴', exact: true })).toBeVisible();
  await expect(first.getByRole('button', { name: 'AI로 다시 쓰기', exact: true })).toBeVisible();
  // The opening scene keeps two lines, so every line of it carries its own seconds.
  for (const seconds of await first.locator('[data-slot="script-line-seconds"]').all()) {
    await expect(seconds).toHaveText(/^약 \d+초$/u);
  }

  await expect(screen.getByRole('button', { name: '이대로 영상 만들기', exact: true })).toHaveCount(1);
  await expect(page.getByRole('button', { name: '이대로 영상 만들기', exact: true })).toHaveCount(1);
});

test('test_10a_the_script_action_floats_over_the_document_without_a_band', async ({ page }) => {
  const screen = await openScript(page);
  const footer = screen.locator('[data-slot="script-footer"]');
  expect(await footer.evaluate((node) => getComputedStyle(node).backgroundColor))
    .toBe('rgba(0, 0, 0, 0)');
  const next = screen.getByRole('button', { name: '이대로 영상 만들기', exact: true });
  // The canon's 18% black shadow is the button's own layer: 55% black at 18/55 opacity.
  const shadow = await next.evaluate((node) => {
    const layer = getComputedStyle(node, '::before');
    return { boxShadow: layer.boxShadow, opacity: Number(layer.opacity) };
  });
  expect(shadow.boxShadow).toContain('0px 4px 14px');
  expect(shadow.opacity).toBeCloseTo(0.18 / 0.55, 3);
  const scenes = screen.locator('[data-slot="script-scenes"]');
  expect(parseFloat(await scenes.evaluate((node) => getComputedStyle(node).paddingBottom)))
    .toBeGreaterThanOrEqual(116);
});

test('test_2_the_confirmed_step_opens_edit_and_a_new_video_starts_clean', async ({ page }) => {
  const screen = await openScript(page);
  const first = firstLine(sceneCards(screen).first());
  await expect(first).toHaveValue('커피를 고르는 세 가지 기준');

  await screen.getByRole('button', { name: '이대로 영상 만들기', exact: true }).click();
  await expect(page.locator('[data-slot="stage-panel"]')).toHaveAttribute('data-stage', 'edit');

  await openStage(page, '대본');
  const back = page.locator('[data-slot="stage-panel"][data-stage="script"]');
  const backLine = firstLine(sceneCards(back).first());
  await expect(backLine).toBeEnabled();
  await backLine.fill('확인한 뒤에도 고칠 수 있어요.');
  await expect(backLine).toHaveValue('확인한 뒤에도 고칠 수 있어요.');

  await page.getByRole('button', { name: '새로 만들기' }).click();
  await page
    .getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })
    .fill('겨울 산책을 즐기는 세 가지 방법');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  await expect(page.getByRole('heading', { name: '컨셉', exact: true })).toBeVisible();
  await openStage(page, '대본');

  const next = page.locator('[data-slot="stage-panel"][data-stage="script"]');
  await expect(firstLine(sceneCards(next).first())).toHaveValue(
    '겨울 산책을 즐기는 세 가지 방법',
  );
  await expect(next.getByRole('button', { name: '이대로 영상 만들기', exact: true })).toBeEnabled();
});

test('test_1_a_new_video_with_the_same_sentence_opens_a_fresh_script', async ({ page }) => {
  const screen = await openScript(page);
  await firstLine(sceneCards(screen).first()).fill('첫 영상에서 고친 대사');
  await screen.getByRole('button', { name: '이대로 영상 만들기', exact: true }).click();
  await expect(page.locator('[data-slot="stage-panel"]')).toHaveAttribute('data-stage', 'edit');

  await page.getByRole('button', { name: '새로 만들기' }).click();
  await page
    .getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })
    .fill('커피를 고르는 세 가지 기준');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  await expect(page.getByRole('heading', { name: '컨셉', exact: true })).toBeVisible();
  await openStage(page, '대본');

  const next = page.locator('[data-slot="stage-panel"][data-stage="script"]');
  await expect(firstLine(sceneCards(next).first())).toHaveValue('커피를 고르는 세 가지 기준');
  await expect(next.getByRole('button', { name: '이대로 영상 만들기', exact: true })).toBeEnabled();
});

test('test_3_the_interface_language_keeps_the_video_script', async ({ page }) => {
  const screen = await openScript(page);
  const line = firstLine(sceneCards(screen).first());
  await line.fill('언어를 바꿔도 남아요.');

  await page.getByRole('button', { name: 'English' }).click();

  await expect(page.getByRole('heading', { name: 'Script', exact: true })).toBeVisible();
  await expect(line).toHaveValue('언어를 바꿔도 남아요.');
});

test('test_10a_the_length_field_applies_the_recommended_count', async ({ page }) => {
  const screen = await openScript(page);

  await screen.getByRole('combobox', { name: '길이', exact: true }).click();
  await page.getByLabel('2분', { exact: true }).click();

  await expect(sceneCards(screen)).toHaveCount(11);
  await expect(screen.getByRole('combobox', { name: '장면 수', exact: true })).toContainText('11');
});

test('test_12_the_scene_buttons_only_move_the_order', async ({ page }) => {
  const screen = await openScript(page);
  const cards = sceneCards(screen);

  const before = await cards.first().locator('[data-slot="script-line-input"]').evaluateAll(
    (nodes) => nodes.map((node) => (node as HTMLTextAreaElement).value),
  );
  const secondBefore = await cards.nth(1).locator('[data-slot="script-line-input"]').evaluateAll(
    (nodes) => nodes.map((node) => (node as HTMLTextAreaElement).value),
  );

  await cards.first().getByRole('button', { name: '아래로 옮기기', exact: true }).click();

  await expect(cards.first().locator('[data-slot="script-line-input"]').first()).toHaveValue(
    secondBefore[0] ?? '',
  );
  await expect(cards.nth(1).locator('[data-slot="script-line-input"]').first()).toHaveValue(
    before[0] ?? '',
  );
});

test('test_2_the_rewrite_control_becomes_stop_and_keeps_the_original_lines', async ({ page }) => {
  const screen = await openScript(page);
  const card = sceneCards(screen).first();
  const line = firstLine(card);
  const original = await line.inputValue();

  await card.getByRole('button', { name: 'AI로 다시 쓰기', exact: true }).click();

  await expect(card.locator('[data-slot="script-working"]')).toBeVisible();
  await expect(card.locator('[data-slot="script-working"]')).toContainText('고치는 중');
  await expect(card.getByRole('button', { name: '멈추기', exact: true })).toBeVisible();

  await card.getByRole('button', { name: '멈추기', exact: true }).click();

  await expect(card.locator('[data-slot="script-working"]')).toHaveCount(0);
  await expect(card.getByRole('button', { name: 'AI로 다시 쓰기', exact: true })).toBeVisible();
  await expect(firstLine(card)).toHaveValue(original);
});

test('test_7_the_card_actions_start_at_the_line_box_edge_and_the_scene_menu_keeps_the_tools_still', async ({ page }) => {
  const screen = await openScript(page);
  const card = sceneCards(screen).first();
  const box = async (locator: Locator) => (await locator.boundingBox())!;
  const lineLeft = (await box(card.locator('.script-line-row').first())).x;
  const rewrite = card.getByRole('button', { name: 'AI로 다시 쓰기', exact: true });

  expect((await box(rewrite)).x).toBeCloseTo(lineLeft, 0);

  const arrows = card.getByRole('button', { name: '위로 옮기기', exact: true });
  const resting = await box(arrows);
  await card.locator('[data-slot="script-scene-menu"]').click();
  await expect(page.getByRole('menu')).toBeVisible();
  expect((await box(arrows)).x).toBe(resting.x);
  await page.keyboard.press('Escape');

  await rewrite.click();
  await expect(card.locator('[data-slot="script-working"]')).toBeVisible();
  expect((await box(card.getByRole('button', { name: '멈추기', exact: true }))).x).toBeCloseTo(lineLeft, 0);
  expect(await card.locator('.script-card').evaluate((el) => getComputedStyle(el).borderTopColor)).not.toBe(
    'rgba(0, 0, 0, 0)',
  );
  await card.getByRole('button', { name: '멈추기', exact: true }).click();

  await rewrite.click();
  await card.locator('[data-slot="script-review"]').waitFor();
  const cancel = card.getByRole('button', { name: '취소', exact: true });
  expect((await box(cancel)).x).toBeCloseTo(lineLeft, 0);
});

test('test_2_a_focused_line_shows_one_grey_border_around_the_whole_box_with_its_seconds', async ({ page }) => {
  const screen = await openScript(page);
  const card = sceneCards(screen).first();
  const row = card.locator('.script-line-row').first();

  await firstLine(card).focus();

  const sign = await row.evaluate((el) => {
    const style = getComputedStyle(el);
    const input = getComputedStyle(el.querySelector('textarea')!);
    return { style: style.outlineStyle, color: style.outlineColor, inputStyle: input.outlineStyle };
  });
  expect(sign.style).toBe('solid');
  expect(sign.color).not.toBe('rgb(49, 130, 246)');
  expect(sign.inputStyle).toBe('none');
  const rowBox = (await row.boundingBox())!;
  const seconds = (await row.locator('[data-slot="script-line-seconds"]').boundingBox())!;
  expect(seconds.x + seconds.width).toBeLessThanOrEqual(rowBox.x + rowBox.width);
});

test('test_5_a_added_line_is_deleted_and_the_top_bar_undo_brings_it_back', async ({ page }) => {
  const screen = await openScript(page);
  const card = sceneCards(screen).first();
  const lines = card.locator('[data-slot="script-line-input"]');
  const count = await lines.count();

  await card.getByRole('button', { name: '대사 줄 추가', exact: true }).click();
  await expect(lines).toHaveCount(count + 1);
  await card.getByRole('button', { name: `장면 1 대사 ${count + 1} 지우기`, exact: true }).click();
  await expect(lines).toHaveCount(count);

  await page.getByRole('button', { name: '되돌리기', exact: true }).click();
  await expect(lines).toHaveCount(count + 1);
});

test('test_6_a_line_grip_reorders_the_lines_of_one_scene', async ({ page }) => {
  const screen = await openScript(page);
  const card = sceneCards(screen).first();
  const lines = card.locator('[data-slot="script-line-input"]');
  const before = await lines.evaluateAll((nodes) => nodes.map((node) => (node as HTMLTextAreaElement).value));

  await card
    .getByRole('button', { name: '장면 1 대사 1 순서 바꾸기', exact: true })
    .dragTo(card.locator('[data-slot="script-line"]').nth(1));

  await expect.poll(() => lines.evaluateAll((nodes) => nodes.map((node) => (node as HTMLTextAreaElement).value))).toEqual([
    before[1],
    before[0],
  ]);
});

test('test_8a_the_rewrite_review_applies_in_place_and_undoes_once', async ({ page }) => {
  const screen = await openScript(page);
  const card = sceneCards(screen).first();
  const original = await firstLine(card).inputValue();

  await card.getByRole('button', { name: 'AI로 다시 쓰기', exact: true }).click();

  const review = card.locator('[data-slot="script-review"]');
  await expect(review).toBeVisible();
  await expect(page.getByRole('button', { name: '되돌리기', exact: true })).toBeDisabled();
  // The opening scene keeps two lines, so its rewrite shows both of them struck.
  await expect(review.locator('del').first()).toContainText('커피를 고르는 세 가지 기준');
  await expect(review).toContainText('다시 말하면, 커피를 고르는 세 가지 기준');

  await review.getByRole('button', { name: '적용', exact: true }).click();

  await expect(review).toHaveCount(0);
  await expect(firstLine(card)).toHaveValue(
    '다시 말하면, 커피를 고르는 세 가지 기준',
  );
  await expect(card.locator('[data-slot="script-changed"]')).toBeVisible();

  await page.getByRole('button', { name: '되돌리기', exact: true }).click();

  await expect(firstLine(card)).toHaveValue(original);
  await expect(card.locator('[data-slot="script-changed"]')).toHaveCount(0);
});

test('test_26_the_tone_field_shows_the_old_and_new_line_and_blocks_the_step', async ({ page }) => {
  const screen = await openScript(page);

  await screen.getByRole('combobox', { name: '말투', exact: true }).click();
  await page.getByRole('option', { name: '~합니다', exact: true }).click();

  const previews = screen.locator('[data-slot="script-tone-preview"]');
  await expect(previews).toHaveCount(5);
  // Every scene now keeps a line the tone changes, so the second scene holds this pair.
  const second = previews.nth(1);
  await expect(second.locator('del').first()).toContainText('길 찾기가 어려워요');
  await expect(second).toContainText('길 찾기가 어렵습니다');
  await expect(screen.getByRole('button', { name: '이대로 영상 만들기', exact: true })).toBeDisabled();
  await expect(
    screen.locator('[data-slot="script-footer"]').getByRole('status'),
  ).toContainText('말투를 바꿀지 먼저 정해 주세요.');

  await screen.getByRole('combobox', { name: '말투', exact: true }).click();
  await page.getByRole('option', { name: '~해요', exact: true }).click();

  await expect(previews).toHaveCount(0);
  await expect(screen.getByRole('button', { name: '이대로 영상 만들기', exact: true })).toBeEnabled();
  await expect(firstLine(sceneCards(screen).first())).toHaveValue(
    '커피를 고르는 세 가지 기준',
  );
});

test('test_2_enter_makes_the_only_line_break', async ({ page }) => {
  const screen = await openScript(page);
  const line = firstLine(sceneCards(screen).first());

  await line.fill('첫 줄');
  await line.press('End');
  await line.press('Enter');
  await line.pressSequentially('둘째 줄');

  await expect(line).toHaveValue('첫 줄\n둘째 줄');
  const breaks = (await line.inputValue()).split('\n').length - 1;
  expect(breaks).toBe(1);

  await line.fill('닫는 따옴표 "이" 앞에서도 줄은 그대로예요.');
  expect(await line.inputValue()).not.toContain('\n');

  await line.fill('가'.repeat(120));
  const box = await line.boundingBox();
  expect(box).not.toBeNull();
  expect(box?.height).toBeLessThan(60);
  const overflow = await line.evaluate((element) => element.scrollWidth > element.clientWidth);
  expect(overflow).toBe(true);
});

test('test_10a_the_document_scrolls_by_the_jump_control_without_a_scrollbar', async ({
  page,
  browserName,
}) => {
  const screen = await openScript(page);

  await screen.getByRole('combobox', { name: '장면 수', exact: true }).click();
  await page.getByRole('option', { name: '11', exact: true }).click();
  await expect(sceneCards(screen)).toHaveCount(11);

  const viewport = page.getByRole('region', { name: '대본 문서', exact: true });
  const jump = page.getByRole('button', { name: '아래로 넘기기', exact: true });
  await expect(jump).toBeVisible();
  await jump.click();
  await expect
    .poll(async () => viewport.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0);

  if (browserName === 'chromium') {
    // scrollbar-width is reported by Chromium; WebKit hides it by the same rule.
    expect(await viewport.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe(
      'none',
    );
  }
});

test('test_23_the_last_row_clears_the_floating_step_button_and_the_page_does_not_overflow', async ({
  page,
}) => {
  for (const size of WIDTHS) {
    const screen = await openScript(page, size);
    const next = screen.getByRole('button', { name: '이대로 영상 만들기', exact: true });
    await expect(next).toBeVisible();
    const nextBox = await next.boundingBox();
    const screenBox = await screen.boundingBox();
    expect(nextBox).not.toBeNull();
    expect(screenBox).not.toBeNull();
    if (nextBox === null || screenBox === null) {
      continue;
    }
    expect(nextBox.x + nextBox.width).toBeLessThanOrEqual(screenBox.x + screenBox.width);
    expect(screenBox.x + screenBox.width - (nextBox.x + nextBox.width)).toBeLessThanOrEqual(32);
    expect(nextBox.y + nextBox.height).toBeGreaterThan(screenBox.y + screenBox.height - 80);

    const cards = sceneCards(screen);
    for (let index = 0; index < (await cards.count()); index += 1) {
      const card = cards.nth(index);
      await card.scrollIntoViewIfNeeded();
      const action = await card.getByRole('button', { name: 'AI로 다시 쓰기', exact: true }).boundingBox();
      expect(action).not.toBeNull();
      for (const input of await card.locator('[data-slot="script-line-input"]').all()) {
        const box = await input.boundingBox();
        expect(box).not.toBeNull();
        if (box === null || action === null) {
          continue;
        }
        const overlap =
          box.x < action.x + action.width &&
          action.x < box.x + box.width &&
          box.y < action.y + action.height &&
          action.y < box.y + box.height;
        expect(overlap).toBe(false);
      }
    }

    // The document keeps enough bottom padding to scroll its last row above
    // the floating action.
    const viewport = screen.locator('.scroll-pane__viewport');
    // The pane scrolls smoothly, so jump without animation before measuring.
    await viewport.evaluate((node) => {
      node.scrollTo({ top: node.scrollHeight, behavior: 'instant' });
    });
    await expect.poll(() => viewport.evaluate(
      (node) => Math.ceil(node.scrollTop + node.clientHeight) >= Math.ceil(node.scrollHeight),
    )).toBe(true);
    const lastCard = await cards.last().boundingBox();
    expect(lastCard).not.toBeNull();
    expect(lastCard!.y + lastCard!.height).toBeLessThan(nextBox.y);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflow).toBe(false);
  }
});

test('test_23_captures_the_script_step_at_1280_and_1920', async ({ page }, testInfo) => {
  for (const size of WIDTHS) {
    await openScript(page, size);
    await capture(page, testInfo, `tests/script/screens/script-${size.width}.png`, true);
  }
});
