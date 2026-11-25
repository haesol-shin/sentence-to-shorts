import { expect, test } from '@playwright/test';

const GALLERY = '/src/gallery/index.html';

test.describe.configure({ mode: 'serial', timeout: 180_000 });

// eslint-disable-next-line no-empty-pattern
test.beforeEach(({}, testInfo) => {
  test.skip(
    testInfo.project.name !== 'chromium-desktop',
    'the gallery evidence runs once in chromium; the app suite owns the other browsers',
  );
});

test('test_10a_copy_tab_previews_both_languages_in_the_linked_case', async ({ page }) => {
  await page.goto(`${GALLERY}?tab=copy`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await expect(page.getByRole('heading', { name: /공통·첫 화면 문구 \d+개/u })).toBeVisible({
    timeout: 120_000,
  });
  await expect(page.getByRole('link', { name: '문구', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );

  await page.locator('.copy-files button').filter({ hasText: '컨셉' }).click();
  await page.getByRole('heading', { name: /컨셉 문구 \d+개/u }).waitFor();
  await page.locator('[data-key="composer.fileTooMany"] button').click();
  await expect(page.locator('.copy-preview')).toHaveAttribute(
    'data-copy-preview-case',
    '18-7-attachments',
  );

  const korean = page.getByLabel('한국어 문구');
  await expect(korean).toBeVisible();
  await korean.fill('글 파일은 {max}개까지 붙일 수 있어요. 빠진 파일: 메모4.txt');
  await expect(page.getByRole('status')).toContainText('저장 안 됨');
  await expect(page.getByRole('status')).toContainText('{names}');
  const save = page.getByRole('button', { name: '저장', exact: true });
  await expect(save).toBeDisabled();

  const preview = page.frameLocator('.copy-preview iframe');
  const errorLine = preview.locator('.composer [data-slot="composer-error"]');
  await expect(errorLine).toContainText('글 파일은 3개까지 붙일 수 있어요. 빠진 파일: 메모4.txt');
  await expect(errorLine).not.toContainText('{max}');

  await page.getByLabel('영어 문구').fill('You can attach up to {max} files. Not attached: {names}');
  await page.getByRole('button', { name: 'English', exact: true }).click();
  await expect(errorLine).toContainText('You can attach up to 3 files. Not attached: 메모4.txt, 메모5.txt');
  await expect(errorLine).not.toContainText('{max}');

  await korean.fill('글 파일은 {max}개까지 붙일 수 있어요. 빠진 파일: {names}');
  await page.getByRole('button', { name: '한국어', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('검사 통과');
  await expect(save).toBeEnabled();

  await page.locator('[data-key="composer.attachmentRemove"] button').click();
  await page.getByLabel('한국어 문구').fill('{name} 지우기');
  await expect(page.locator('.copy-preview')).toHaveAttribute(
    'data-copy-preview-case',
    '18-7-attachments',
  );
  await expect(
    page.frameLocator('.copy-preview iframe').getByRole('button', {
      name: '참고_영상.mp4 지우기',
    }),
  ).toBeVisible();

  await page.locator('.copy-files button').filter({ hasText: '공통·첫 화면' }).click();
  await page.getByRole('heading', { name: /공통·첫 화면 문구 \d+개/u }).waitFor();
  await page.locator('[data-key="apiKey.save"] button').click();
  await expect(page.getByText('이 문구를 그리는 화면 사례가 없어요.')).toBeVisible();
  await expect(page.locator('.copy-usages')).toContainText('src/app/api-key-block.tsx:');

  await page.locator('[data-key="nav.newVideo"] button').click();
  await expect(page.locator('.copy-usages')).toContainText('src/app/shell/sidebar.tsx:');
});

test('test_10a_copy_linked_case_and_menu_render_catalog_copy', async ({ page }) => {
  await page.goto(`${GALLERY}?tab=copy`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await expect(page.getByRole('heading', { name: /공통·첫 화면 문구 \d+개/u })).toBeVisible({
    timeout: 120_000,
  });
  await page.locator('.copy-files button').filter({ hasText: '컨셉' }).click();
  await page.getByRole('heading', { name: /컨셉 문구 \d+개/u }).waitFor();

  await page.locator('[data-key="composer.fileTooMany"] button').click();
  const errorHref = await page.getByRole('link', { name: '화면 사례로 이동' }).getAttribute('href');
  expect(errorHref).toBeTruthy();
  await page.goto(new URL(errorHref ?? '', page.url()).toString(), { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.composer [data-slot="composer-error"]')).toContainText(
    '붙이지 않은 파일: 메모4.txt, 메모5.txt',
  );

  for (const [key, saved] of [
    ['composer.addLink', '영상 링크 붙여넣기'],
    ['composer.addBgm', 'BGM 올리기'],
  ] as const) {
    await page.goto(`${GALLERY}?tab=copy`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: /공통·첫 화면 문구 \d+개/u }).waitFor();
    await page.locator('.copy-files button').filter({ hasText: '컨셉' }).click();
    await page.getByRole('heading', { name: /컨셉 문구 \d+개/u }).waitFor();
    await page.locator(`[data-key="${key}"] button`).click();
    const frame = page.frameLocator('.copy-preview iframe');
    await expect(frame.getByText(saved, { exact: true })).toBeVisible();
    await expect(page.locator('.copy-usages')).toContainText('src/app/shell/composer.tsx');
    const href = await page.getByRole('link', { name: '화면 사례로 이동' }).getAttribute('href');
    expect(href).toBeTruthy();
    await page.goto(new URL(href ?? '', page.url()).toString(), { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(saved, { exact: true })).toBeVisible();
  }
});
