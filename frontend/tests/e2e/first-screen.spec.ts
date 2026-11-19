import { expect, test } from '@playwright/test';

const SENTENCE = '커피를 고르는 세 가지 기준';

function projectId(body: unknown): string {
  if (typeof body === 'object' && body !== null && 'id' in body && typeof body.id === 'string') {
    return body.id;
  }
  throw new Error('the project response has no id');
}

test('test_10a_the_first_screen_creates_a_project_on_the_fixture_backend', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '어떤 영상을 만들까요?' })).toBeVisible();
  await expect(page.locator('[data-slot="first-cards"] button')).toHaveCount(3);

  const created = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === '/api/v1/projects',
  );

  await page
    .getByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })
    .fill(SENTENCE);
  await page.getByRole('button', { name: '보내기', exact: true }).click();

  const response = await created;
  expect(response.status()).toBe(201);
  const id = projectId(await response.json());

  const stored = await page.request.get(`/api/v1/projects/${id}`);
  expect(stored.ok()).toBe(true);
  expect(projectId(await stored.json())).toBe(id);

  await expect(page.getByRole('heading', { name: '컨셉', exact: true })).toBeVisible();
});
