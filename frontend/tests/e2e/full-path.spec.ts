import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { expect, test, type Locator, type Page } from '@playwright/test';

// The fixture model only knows this sentence with the "just three" card, and
// the script it recorded for it.
const SENTENCE = '커피 고르는 법';
const SENTENCE_FIELD = '만들고 싶은 영상을 한 문장으로 적어 주세요';
const SCRIPT_LINES = [
  SENTENCE,
  '첫째, 신선한 원두',
  '둘째, 로스팅 정도',
  '셋째, 분쇄 굵기',
  '신선도, 로스팅, 분쇄',
];
const REWRITTEN_LINE = '핵심만 기억해요';
const REWRITE_REQUEST = '이 장면을 핵심만 짧게 줄여 줘';
const SHOTS = process.env.E2E_SHOTS_DIR ?? resolve(process.cwd(), '../.local/shots');

interface Session {
  csrf: string;
  videoId: string;
}

interface SceneView {
  lines: { display_text: string }[];
}

interface VideoBody {
  video: {
    id: string;
    project_id: string;
    revision: number;
    stage: string;
    topic: string;
    material: { text: string }[];
    scene_order: string[];
    scenes: Record<string, SceneView>;
    settings: { visual: { theme_id: string } };
  };
  build: { actual_ms: number | null; final: { state: string; artifact: { id: string } | null } };
}

async function shot(page: Page, name: string): Promise<void> {
  mkdirSync(SHOTS, { recursive: true });
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: resolve(SHOTS, `${name}-${width}.png`) });
}

/** The token and the video id the page itself used, so a request made beside it is the same user. */
function follow(page: Page): Session {
  const session: Session = { csrf: '', videoId: '' };
  page.on('request', (request) => {
    const token = request.headers()['x-csrf-token'];
    if (token !== undefined) session.csrf = token;
    const found = /\/videos\/(v_[^/]+)\//.exec(request.url());
    if (found !== null) session.videoId = found[1];
  });
  return session;
}

async function readVideo(page: Page, videoId: string): Promise<VideoBody> {
  const response = await page.request.get(`/api/v1/videos/${videoId}`);
  expect(response.ok()).toBe(true);
  return (await response.json()) as VideoBody;
}

async function sendSentence(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: /딱 3가지만/ }).click();
  await page.getByRole('textbox', { name: SENTENCE_FIELD }).fill(SENTENCE);
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  await expect(page.getByRole('heading', { name: '컨셉', exact: true })).toBeVisible();
  // The draft has landed once the concept shows the topic the model wrote.
  await expect(page.getByText('커피를 고르는 기준')).toBeVisible({ timeout: 60_000 });
}

async function openStage(page: Page, stage: string): Promise<void> {
  const flow = page.getByRole('navigation', { name: '단계' });
  if (await flow.isVisible()) {
    await flow.getByRole('button', { name: stage }).click();
    return;
  }
  await page.getByRole('button', { name: '단계 열기' }).click();
  await page.getByRole('menuitem', { name: stage }).click();
}

async function confirmConcept(page: Page): Promise<void> {
  await page.getByRole('button', { name: '정하고 대본 만들기' }).click();
  const confirmed = page.waitForResponse((response) => response.url().endsWith('/concept/confirm'));
  await page.getByRole('dialog').getByRole('button', { name: '정하고 대본 만들기' }).click();
  expect((await confirmed).status()).toBe(200);
}

async function confirmScript(page: Page): Promise<void> {
  await openStage(page, '대본');
  const hook = page.getByRole('textbox', { name: '장면 1 대사 1' });
  await expect(hook).toBeVisible({ timeout: 60_000 });
  await expect(hook).toHaveValue(SCRIPT_LINES[0]);
  await page.getByRole('button', { name: '이대로 영상 만들기' }).click();
}

/** The scene dialog on the edit screen, then the precheck panel the export screen opens with. */
async function confirmScenes(page: Page): Promise<void> {
  await page.getByRole('button', { name: '영상 만들기', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '영상 만들기' }).click();
  await expect(page.getByRole('region', { name: '출력 전 확인' })).toBeVisible({ timeout: 120_000 });
}

async function waitForJob(page: Page, jobId: string): Promise<{ result: { artifacts: { final: string }; rebuilt_scene_ids: string[] } }> {
  let job: { state: string } = { state: 'queued' };
  await expect
    .poll(
      async () => {
        job = (await (await page.request.get(`/api/v1/jobs/${jobId}`)).json()) as { state: string };
        return job.state;
      },
      { timeout: 240_000, intervals: [1000] },
    )
    .toBe('succeeded');
  return job as never;
}

/** Presses the export screen's own start button and returns the job it started. */
async function generate(page: Page): Promise<string> {
  const start = page.getByRole('button', { name: '영상 만들기', exact: true });
  await expect(start).toBeEnabled({ timeout: 60_000 });
  const started = page.waitForResponse((response) => response.url().endsWith('/generate'));
  await start.click();
  const response = await started;
  expect(response.status()).toBe(202);
  return ((await response.json()) as { id: string }).id;
}

/** The finished video, shown in the page or in a dialog depending on the width. */
function resultView(page: Page): Locator {
  return page.getByRole('region', { name: '영상 결과' }).or(page.getByRole('dialog', { name: '영상' }));
}

async function reopenResult(page: Page): Promise<void> {
  await page.getByRole('button', { name: '편집으로' }).click();
  await openStage(page, '내보내기');
  await expect(resultView(page)).toBeVisible({ timeout: 30_000 });
}

test('test_1_one_sentence_runs_to_a_result_edit_undo_and_a_next_video', async ({ page }) => {
  test.setTimeout(480_000);
  const session = follow(page);
  const width = page.viewportSize()?.width ?? 0;

  await test.step('one sentence starts a draft and the concept is confirmed', async () => {
    await sendSentence(page);
    await shot(page, 'concept');
    await confirmConcept(page);
    const stored = await readVideo(page, session.videoId);
    expect(stored.video.stage).toBe('concept_confirmed');
  });

  await test.step('the script and the scenes are confirmed', async () => {
    await confirmScript(page);
    await shot(page, 'edit');
    await confirmScenes(page);
    const stored = await readVideo(page, session.videoId);
    expect(stored.video.stage).toBe('scenes_confirmed');
    expect(stored.video.scene_order.map((id) => stored.video.scenes[id].lines[0].display_text)).toEqual(SCRIPT_LINES);
  });

  let firstFinal = '';
  await test.step('the result plays with the captions the server holds', async () => {
    const first = await waitForJob(page, await generate(page));
    firstFinal = first.result.artifacts.final;
    // The button leaves the page on the export screen, which shows the result.
    await expect(resultView(page)).toBeVisible({ timeout: 60_000 });
    const video = resultView(page).locator('video');
    const stored = await readVideo(page, session.videoId);
    await expect
      .poll(() => video.evaluate((element: HTMLVideoElement) => element.duration), { timeout: 30_000 })
      .toBeGreaterThan(0);
    const duration = await video.evaluate((element: HTMLVideoElement) => element.duration);
    expect(Math.abs(duration * 1000 - (stored.build.actual_ms ?? -1))).toBeLessThan(300);

    const [movie] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'mp4 저장' }).click(),
    ]);
    expect(movie.suggestedFilename()).toMatch(/\.mp4$/);
    expect(await movie.failure()).toBeNull();

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: '자막 저장' }).click(),
    ]);
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(chunk as Buffer);
    const cues = Buffer.concat(chunks)
      .toString('utf-8')
      .trim()
      .split(/\r?\n\r?\n/)
      .map((block) => block.split(/\r?\n/));
    expect(cues.map((cue) => cue.slice(2).join('\n'))).toEqual(SCRIPT_LINES);
    const end = /--> (\d+):(\d+):(\d+),(\d+)$/.exec(cues[cues.length - 1][1]);
    expect(end).not.toBeNull();
    const endMs = ((Number(end?.[1]) * 60 + Number(end?.[2])) * 60 + Number(end?.[3])) * 1000 + Number(end?.[4]);
    expect(endMs).toBeLessThanOrEqual(duration * 1000 + 300);
    await shot(page, 'result');
  });

  await test.step('scene 3 is edited, compared and applied, then only it is rebuilt', async () => {
    await page.getByRole('button', { name: '편집으로' }).click();
    await page.getByRole('region', { name: '장면' }).getByRole('button', { name: '두 번째' }).click();
    // The request goes through the chat composer, the way a user asks for a rewrite.
    const request = page.getByRole('textbox', { name: '고칠 점을 적어 주세요' });
    await request.fill(REWRITE_REQUEST);
    await page.getByRole('button', { name: '보내기', exact: true }).click();

    const review = page.getByRole('dialog', { name: '장면을 바꿀까요?' });
    await expect(review).toBeVisible({ timeout: 60_000 });
    await expect(review.getByText('둘째, 로스팅 정도')).toBeVisible();
    await expect(review.getByText(REWRITTEN_LINE)).toBeVisible();
    await shot(page, 'compare');
    await page.getByRole('dialog', { name: '장면을 바꿀까요?' }).getByRole('button', { name: '바꾸기' }).click();
    await expect(page.getByRole('dialog', { name: '장면을 바꿀까요?' })).toBeHidden();
    const applied = await readVideo(page, session.videoId);
    const target = applied.video.scene_order[2];
    expect(applied.video.scenes[target].lines.map((entry) => entry.display_text)).toEqual([REWRITTEN_LINE]);

    await confirmScenes(page);
    const second = await waitForJob(page, await generate(page));
    expect(second.result.rebuilt_scene_ids).toEqual([target]);
    expect(second.result.artifacts.final).not.toBe(firstFinal);
  });

  await test.step('undo brings the earlier line and the earlier video back', async () => {
    await reopenResult(page);
    await page.getByRole('button', { name: '편집으로' }).click();
    await page.getByRole('region', { name: '장면' }).getByRole('button', { name: '두 번째' }).click();
    await page.getByRole('button', { name: '되돌리기' }).click();
    await expect(page.getByRole('button', { name: '되돌리기' })).toBeDisabled();
    const restored = await readVideo(page, session.videoId);
    const target = restored.video.scene_order[2];
    expect(restored.video.scenes[target].lines.map((entry) => entry.display_text)).toEqual(['둘째, 로스팅 정도']);
    expect(restored.build.final.state).toBe('fresh');
    expect(restored.build.final.artifact?.id).toBe(firstFinal);

    // Keeping a proposed change closes the dialog and hands focus back to the save control.
    const line = page.getByRole('region', { name: '장면 설정' }).getByRole('textbox', { name: '화면 글 1' });
    await line.fill(REWRITTEN_LINE);
    const save = page.getByRole('button', { name: '줄 저장' });
    await save.focus();
    await page.keyboard.press('Enter');
    const review = page.getByRole('dialog', { name: '장면을 바꿀까요?' });
    await expect(review).toBeVisible();
    await review.getByRole('button', { name: '그대로 두기' }).focus();
    await page.keyboard.press('Enter');
    await expect(review).toBeHidden();
    await expect(save).toBeFocused();
  });

  await test.step('the next video starts from the same settings with nothing carried over', async () => {
    await openStage(page, '내보내기');
    await page.getByRole('button', { name: '결과 카드 닫기' }).click();
    await page.getByRole('button', { name: '다음 영상도 이 설정으로' }).click();
    await expect(page.getByText('다음 영상도 이 설정으로 시작해요.')).toBeVisible();
    const previous = await readVideo(page, session.videoId);
    const created = page.waitForRequest(
      (request) => request.method() === 'POST' && request.url().endsWith(`/projects/${previous.video.project_id}/videos`),
    );
    await page.getByRole('button', { name: '새로 만들기' }).click();
    await page.getByRole('textbox', { name: SENTENCE_FIELD }).fill(SENTENCE);
    await page.getByRole('button', { name: '보내기', exact: true }).click();
    const body = (await created).postDataJSON() as { preset_id: string | null };
    expect(body.preset_id).not.toBeNull();
    await expect(page.getByRole('heading', { name: '컨셉', exact: true })).toBeVisible();
    await expect.poll(() => session.videoId).not.toBe(previous.video.id);
    // The draft of the next video lands too: the concept shows the topic the model wrote for it.
    await expect(page.getByText('원두를 고르는 기준')).toBeVisible({ timeout: 60_000 });
    const next = await readVideo(page, session.videoId);
    expect(next.video.topic).toBe('원두를 고르는 기준');
    expect(next.video.project_id).toBe(previous.video.project_id);
    expect(next.video.material).toEqual([]);
    // Its own script, not the first video's scenes.
    expect(next.video.scene_order).toHaveLength(5);
    expect(next.video.scene_order.map((id) => next.video.scenes[id].lines[0].display_text)).not.toEqual(SCRIPT_LINES);
    expect(next.video.scene_order).not.toContain(previous.video.scene_order[0]);
    await shot(page, 'next');
  });
  expect(width).toBeGreaterThan(0);
});

test('test_7_the_concept_screen_saves_a_text_material_and_a_setting_on_the_backend', async ({ page }) => {
  test.setTimeout(240_000);
  const session = follow(page);
  await sendSentence(page);

  const input = page.locator('input[type="file"][data-kind="text"]').first();
  await input.setInputFiles({
    name: 'notes.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('원두는 볶은 날짜가 가까울수록 향이 좋다.', 'utf-8'),
  });
  const added = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith('/changes'),
  );
  await page.getByRole('button', { name: '보내기', exact: true }).and(page.locator(':enabled')).click();
  expect((await added).status()).toBe(200);
  await expect.poll(async () => (await readVideo(page, session.videoId)).video.material.length).toBe(1);
  const stored = await readVideo(page, session.videoId);
  expect(stored.video.material[0].text).toContain('볶은 날짜');

  await page.getByRole('combobox', { name: '테마' }).selectOption({ label: '달밤' });
  await confirmConcept(page);
  const confirmed = await readVideo(page, session.videoId);
  expect(confirmed.video.stage).toBe('concept_confirmed');
  expect(confirmed.video.settings.visual.theme_id).not.toBe(stored.video.settings.visual.theme_id);
  expect(confirmed.video.material).toHaveLength(1);
});

test('test_10a_keyboard_and_reduced_motion_on_the_first_screen', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const card = page.getByRole('button', { name: /딱 3가지만/ });
  await card.focus();
  await page.keyboard.press('Enter');
  await expect(card).toHaveAttribute('aria-pressed', 'true');
  // The chosen card is a chip with a named control that removes it.
  await expect(page.getByRole('button', { name: '고른 카드 지우기' })).toBeVisible();
  await page.getByRole('button', { name: '고른 카드 지우기' }).focus();
  await page.keyboard.press('Enter');
  await expect(card).toHaveAttribute('aria-pressed', 'false');

  const field = page.getByRole('textbox', { name: SENTENCE_FIELD });
  await field.focus();
  await page.keyboard.type(SENTENCE);
  const send = page.getByRole('button', { name: '보내기', exact: true });
  await expect(send).toBeEnabled();
  const duration = await send.evaluate((element) => getComputedStyle(element).transitionDuration);
  expect(duration.split(',').every((value) => parseFloat(value) === 0)).toBe(true);
  // The input and the send button sit apart, so the button is never covered.
  const fieldBox = await field.boundingBox();
  const sendBox = await send.boundingBox();
  expect(fieldBox).not.toBeNull();
  expect(sendBox).not.toBeNull();
  if (fieldBox !== null && sendBox !== null) {
    const overlaps =
      sendBox.x < fieldBox.x + fieldBox.width &&
      sendBox.x + sendBox.width > fieldBox.x &&
      sendBox.y < fieldBox.y + fieldBox.height &&
      sendBox.y + sendBox.height > fieldBox.y;
    expect(overlaps).toBe(false);
  }
  await shot(page, 'first');
});
