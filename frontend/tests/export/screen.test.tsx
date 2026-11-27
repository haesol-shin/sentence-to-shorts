import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { configureExport, rearmAutoStart } from '@/features/export/store';
import { ApiProblemError } from '@/shared/api/client';

import { builtView, FINAL_ID, job, METRICS, REPORT, renderExport, stubApi, unbuiltView } from './fixtures';

const FACT_LABELS = ['길이', '형식', '자막', '사용량'];
const SCENE_NUMBERS = ['장면 1', '장면 2', '장면 3'];

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  configureExport(null);
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

/** Records the files a click on a download control asks for. */
function recordDownloads(): string[] {
  const hrefs: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(this: HTMLAnchorElement) {
    hrefs.push(this.getAttribute('href') ?? '');
  });
  return hrefs;
}

async function closeCard(): Promise<void> {
  fireEvent.click(await screen.findByRole('button', { name: '결과 카드 닫기' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
}

test('test_30_the_check_before_output_shows_the_four_items_and_no_guarantee', async () => {
  const api = stubApi();
  renderExport(unbuiltView(), api);

  expect(await screen.findByText(REPORT.opening_promise)).toBeTruthy();
  expect(screen.getByText(REPORT.ending_answer)).toBeTruthy();
  const claims = document.querySelector<HTMLElement>('[data-slot="precheck-claims"]');
  expect(claims?.textContent).toContain('장면 2');
  expect(claims?.textContent).toContain('물은 93도가 좋다');
  expect(claims?.textContent).toContain('자료 원문: 물의 온도를 93도로 맞춘다.');
  expect(claims?.textContent).not.toContain('m_0material');
  expect(claims?.textContent).toContain('올린 자료에서 근거를 찾지 못했어요');
  expect(document.querySelector('[data-slot="precheck-assumptions"]')?.textContent).toContain('장면 1');
  expect(screen.getByText(/사실인지를 검증하거나 보증하지 않아요/)).toBeTruthy();
  expect(api.startPrecheck).toHaveBeenCalledWith(unbuiltView().video.id, 1);
  expect(screen.queryByRole('dialog')).toBeNull();
});

test('test_30_a_finished_check_is_not_asked_for_again_for_the_same_revision', async () => {
  const api = stubApi();
  renderExport(unbuiltView(), api);
  await screen.findByText(REPORT.opening_promise);
  cleanup();

  renderExport(unbuiltView(), api, { sameSession: true });

  expect(await screen.findByText(REPORT.opening_promise)).toBeTruthy();
  expect(api.startPrecheck).toHaveBeenCalledTimes(1);
});

test('test_30_a_failed_check_can_run_again_and_does_not_block_editing', async () => {
  const api = stubApi({ readJob: vi.fn(async () => job('precheck', 'failed')) });
  renderExport(unbuiltView(), api);

  expect(await screen.findByText('출력 전 확인을 하지 못했어요.')).toBeTruthy();
  expect(screen.getByRole('button', { name: '편집으로' })).toBeTruthy();
  expect((screen.getByRole('button', { name: '영상 만들기' }) as HTMLButtonElement).disabled).toBe(true);

  api.readJob.mockResolvedValue(job('precheck', 'succeeded', { precheck: REPORT }));
  fireEvent.click(screen.getByRole('button', { name: '다시 확인' }));
  expect(await screen.findByText(REPORT.opening_promise)).toBeTruthy();
  expect((screen.getByRole('button', { name: '영상 만들기' }) as HTMLButtonElement).disabled).toBe(false);
});

test('test_30_a_check_with_nothing_to_look_at_starts_the_making_without_a_second_press', async () => {
  const view = unbuiltView();
  view.video.material = [];
  const onStart = vi.fn(async () => true);
  const onOpenEdit = vi.fn();
  renderExport(view, stubApi(), { onStart, onOpenEdit });

  await waitFor(() => expect(onOpenEdit).toHaveBeenCalledTimes(1));
  expect(onStart).toHaveBeenCalledTimes(1);
  expect(onStart).toHaveBeenCalledWith(view.video.revision);
  expect(screen.queryByText(REPORT.opening_promise)).toBeNull();
  expect(screen.queryByRole('button', { name: '영상 만들기' })).toBeNull();
});

test('test_30_a_check_with_a_claim_the_material_does_not_back_waits_for_the_press', async () => {
  const onStart = vi.fn(async () => true);
  renderExport(unbuiltView(), stubApi(), { onStart });
  await screen.findByText(REPORT.opening_promise);

  expect(onStart).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: '영상 만들기' })).toBeTruthy();
});

test('test_30_a_start_the_server_refuses_to_retry_stays_on_the_check_with_its_actions', async () => {
  const view = unbuiltView();
  view.video.material = [];
  const onStart = vi.fn(async () => {
    throw new ApiProblemError({
      code: 'job_not_retryable',
      detail: '',
      errors: [],
      instance: '/api/v1/videos/v_0test00000000000000000000/generate',
      message_key: 'error.job_not_retryable',
      retryable: false,
      status: 409,
      title: 'Conflict',
      type: 'about:blank',
    });
  });
  const onOpenEdit = vi.fn();
  renderExport(view, stubApi(), { onStart, onOpenEdit });

  // The check found nothing, so the making starts by itself and the refusal lands here.
  expect(await screen.findByText('이 작업은 다시 시도할 수 없어요.')).toBeTruthy();
  expect(onStart).toHaveBeenCalledTimes(1);
  expect(screen.getByText(REPORT.opening_promise)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '영상 만들기' }));
  await waitFor(() => expect(onStart).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole('button', { name: '편집으로' }));
  expect(onOpenEdit).toHaveBeenCalled();
});

test('test_30_a_failed_make_request_keeps_the_check_visible', async () => {
  renderExport(unbuiltView(), stubApi(), { onStart: async () => false });
  await screen.findByText(REPORT.opening_promise);
  fireEvent.click(screen.getByRole('button', { name: '영상 만들기' }));
  expect(await screen.findByText(/영상을 만들기 시작하지 못했어요/)).toBeTruthy();
  expect(screen.getByText(REPORT.opening_promise)).toBeTruthy();
});

test('test_30_the_check_waits_for_the_edit_step_to_confirm_the_scenes', async () => {
  const view = unbuiltView();
  view.video.stage = 'script_confirmed';
  const api = stubApi();
  renderExport(view, api);

  expect(await screen.findByText('편집에서 영상 만들기를 눌러 장면을 확인해 주세요.')).toBeTruthy();
  expect(api.startPrecheck).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: '영상 만들기' })).toBeNull();
});

test('test_10a_a_running_job_shows_no_progress_and_no_cancel_on_the_export_screen', async () => {
  const view = unbuiltView();
  view.open_jobs = [job('generate', 'running').id];
  const active = job('generate', 'running');
  const api = stubApi({ jobs: async () => [active], readJob: async () => active });
  renderExport(view, api);

  expect(await screen.findByText('영상을 만드는 중이에요')).toBeTruthy();
  expect(screen.queryByRole('progressbar')).toBeNull();
  expect(screen.queryByRole('button', { name: /멈추|취소|중지|stop|cancel/iu })).toBeNull();
  expect(document.querySelector('[data-slot="export-main"]')?.textContent).not.toMatch(/\d+\s*\/\s*\d+/u);
  expect(api.startPrecheck).not.toHaveBeenCalled();
  expect(screen.queryByRole('dialog')).toBeNull();
});

test('test_29_partial_mp4_does_not_open_the_result_until_the_same_job_finishes_and_captions_reload', async () => {
  const partial = builtView();
  partial.build.srt = unbuiltView().build.srt;
  const active = job('generate', 'running');
  partial.open_jobs = [active.id];
  const complete: typeof active = { ...active, state: 'succeeded' };
  let finish!: (completed: typeof active) => void;
  const watching = new Promise<typeof active>((resolve) => { finish = resolve; });
  const api = stubApi({
    loadVideo: async (_id, seed) => seed ?? builtView(),
    jobs: async () => [active],
    readJob: async () => watching,
  });
  renderExport(partial, api);

  await screen.findByText('영상을 만드는 중이에요');
  expect((screen.getByRole('button', { name: 'mp4 저장' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole('dialog')).toBeNull();
  finish(complete);
  const card = await screen.findByRole('dialog', { name: '영상을 다 만들었어요' });
  expect((within(card).getByRole('button', { name: '자막 저장' }) as HTMLButtonElement).disabled).toBe(false);
});

test('test_27_a_failed_generate_names_the_step_and_retries_that_job', async () => {
  const failed = job('generate', 'failed');
  failed.error = { stage: 'clip', scene_id: null, code: 'internal', retryable: true, detail: {} };
  const retry = vi.fn(async () => true);
  renderExport(builtView(), stubApi({ jobs: async () => [failed] }), { onRetryGeneration: retry });

  expect(await screen.findByText('멈춘 부분: 장면 만들기')).toBeTruthy();
  expect((screen.getByRole('button', { name: 'mp4 저장' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '실패한 부분 다시 시도' }));
  expect(retry).toHaveBeenCalledWith(failed);
});

test('test_10a_the_result_card_opens_only_after_the_video_is_made', async () => {
  renderExport(unbuiltView(), stubApi());
  await screen.findByText(REPORT.opening_promise);
  expect(screen.queryByRole('dialog')).toBeNull();
  cleanup();
  configureExport(null);

  renderExport(builtView(), stubApi());
  expect(await screen.findByRole('dialog', { name: '영상을 다 만들었어요' })).toBeTruthy();
});

test('test_10a_the_result_card_comes_back_for_a_new_video_only', async () => {
  renderExport(builtView(), stubApi());
  await closeCard();
  cleanup();
  configureExport(null);

  renderExport(builtView(), stubApi());
  await waitFor(() =>
    expect((screen.getByRole('button', { name: '자막 저장' }) as HTMLButtonElement).disabled).toBe(false),
  );
  expect(screen.queryByRole('dialog')).toBeNull();
  cleanup();
  configureExport(null);

  const next = builtView();
  next.build.final.artifact = { id: 'a_0final20000000000000000000', digest: '0'.repeat(64), cache_key: '0'.repeat(64) };
  renderExport(next, stubApi());
  expect(await screen.findByRole('dialog', { name: '영상을 다 만들었어요' })).toBeTruthy();
});

test('test_10a_the_result_card_has_the_x_and_the_bottom_row_and_nothing_else_to_close', async () => {
  renderExport(builtView(), stubApi());
  const card = await screen.findByRole('dialog', { name: '영상을 다 만들었어요' });

  const names = within(card).getAllByRole('button').map((button) => button.getAttribute('aria-label') ?? button.textContent);
  expect(names).toEqual(
    expect.arrayContaining(['결과 카드 닫기', '재생', '소리 끄기', '자막 저장', '사용량 보기', '편집으로', 'mp4 저장']),
  );
  for (const forbidden of ['닫기', '크게 보기', '이 영상으로 새 영상 만들기']) {
    expect(names).not.toContain(forbidden);
  }
  expect(card.textContent).not.toMatch(/크게 보기|이 영상으로 새 영상 만들기/u);

  const labels = Array.from(card.querySelectorAll('dt')).map((term) => term.textContent);
  expect(labels).toEqual(FACT_LABELS);
  const bottom = Array.from(card.querySelectorAll('.export-result__actions button')).map((button) => button.textContent);
  expect(bottom).toEqual(['편집으로', 'mp4 저장']);
  expect(card.querySelector('button.focus-ring--inset')?.getAttribute('aria-label')).toBe('결과 카드 닫기');
});

test('test_10a_a_video_that_fails_to_play_announces_the_reason_outside_the_picture', async () => {
  renderExport(builtView(), stubApi());
  const card = await screen.findByRole('dialog', { name: '영상을 다 만들었어요' });
  const video = within(card).getByLabelText('영상 미리보기', { selector: 'video' });

  fireEvent.error(video);

  const reason = within(card).getByRole('alert');
  expect(reason.textContent).toBe('영상을 재생하지 못했어요');
  expect(reason.closest('[role="img"]')).toBeNull();
});

test('test_10a_the_card_edit_button_asks_for_the_edit_step_and_closes_the_card', async () => {
  const onOpenEdit = vi.fn();
  renderExport(builtView(), stubApi(), { onOpenEdit });
  const card = await screen.findByRole('dialog', { name: '영상을 다 만들었어요' });

  fireEvent.click(within(card).getByRole('button', { name: '편집으로' }));

  await waitFor(() => expect(onOpenEdit).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

test('test_10a_closing_the_card_with_the_x_lands_on_the_edit_step_not_the_export_panel', async () => {
  const onOpenEdit = vi.fn();
  renderExport(builtView(), stubApi(), { onOpenEdit });
  const card = await screen.findByRole('dialog', { name: '영상을 다 만들었어요' });

  fireEvent.click(within(card).getByRole('button', { name: '결과 카드 닫기' }));

  await waitFor(() => expect(onOpenEdit).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

test('test_13_the_save_buttons_download_the_mp4_and_the_caption_file', async () => {
  const hrefs = recordDownloads();
  const view = builtView();
  renderExport(view, stubApi());
  await closeCard();

  fireEvent.click(screen.getByRole('button', { name: 'mp4 저장' }));
  fireEvent.click(screen.getByRole('button', { name: '자막 저장' }));

  expect(hrefs).toEqual([
    `/api/v1/videos/${view.video.id}/download/mp4`,
    `/api/v1/videos/${view.video.id}/download/srt`,
  ]);
  const player = document.querySelector<HTMLVideoElement>('[data-slot="result-video"]');
  expect(player?.getAttribute('src')).toBe(`/api/v1/artifacts/${FINAL_ID}`);
});

test('test_13_saving_the_mp4_says_where_the_file_went', async () => {
  recordDownloads();
  renderExport(builtView(), stubApi());
  const card = await screen.findByRole('dialog');

  fireEvent.click(within(card).getByRole('button', { name: 'mp4 저장' }));

  expect(await screen.findByText('mp4 파일을 저장했어요. 다운로드 폴더를 확인해 주세요.')).toBeTruthy();
});

test('test_29_the_caption_button_is_named_for_the_file_use_and_srt_stays_out_of_the_page', async () => {
  renderExport(builtView(), stubApi());
  await closeCard();

  expect(screen.getByRole('button', { name: '자막 저장' })).toBeTruthy();
  expect(document.body.textContent).not.toContain('SRT');
});

test('test_29_the_caption_button_waits_until_the_caption_file_exists', async () => {
  const view = builtView();
  view.build.srt = { state: 'missing', cache_key: null, artifact: null, error_code: null };
  renderExport(view, stubApi());
  await closeCard();

  expect((screen.getByRole('button', { name: '자막 저장' }) as HTMLButtonElement).disabled).toBe(true);
});

test('test_10a_the_top_bar_save_is_a_named_primary_button_that_dims_until_the_file_exists', async () => {
  renderExport(unbuiltView(), stubApi());
  await screen.findByText(REPORT.opening_promise);
  const dimmed = screen.getByRole('button', { name: 'mp4 저장' }) as HTMLButtonElement;
  expect(dimmed.disabled).toBe(true);
  expect(dimmed.classList.contains('button--primary')).toBe(true);
  expect(dimmed.classList.contains('button--md')).toBe(true);
  cleanup();
  configureExport(null);

  renderExport(builtView(), stubApi());
  await closeCard();
  const ready = screen.getByRole('button', { name: 'mp4 저장' }) as HTMLButtonElement;
  expect(ready.disabled).toBe(false);
  expect(ready.getAttribute('data-slot')).toBe('next-action');
});

test('test_27_an_unknown_cost_and_unknown_tokens_read_unconfirmed', async () => {
  const api = stubApi({
    metrics: vi.fn(async () => ({ ...METRICS, input_tokens: null, output_tokens: null, cost_micro_usd: null })),
  });
  renderExport(builtView(), api);
  await closeCard();

  const usage = document.querySelector<HTMLElement>('[data-slot="export-usage"]');
  await waitFor(() => expect(usage?.textContent).toContain('1분 23초'));
  expect(document.querySelector('[data-slot="usage-cost"]')?.textContent).toBe('미확인');
  const facts = document.querySelector<HTMLElement>('[data-slot="result-facts"]');
  expect(facts?.textContent).toContain('미확인');
  expect(facts?.textContent).not.toContain('토큰');
});

test('test_27_known_usage_shows_time_tokens_cost_and_the_rebuilt_scenes', async () => {
  const run = job('generate', 'succeeded', { rebuilt_scene_ids: ['s_0scene2000000000000000000'] });
  run.started_at = '2026-11-20T00:00:00Z';
  run.ended_at = '2026-11-20T00:00:12Z';
  renderExport(builtView(), stubApi({ jobs: async () => [run] }));
  await closeCard();

  const usage = document.querySelector<HTMLElement>('[data-slot="export-usage"]');
  await waitFor(() => expect(usage?.textContent).toContain('1분 23초'));
  expect(usage?.textContent).toContain('41초');
  expect(usage?.textContent).toContain('12초');
  expect(usage?.textContent).not.toContain('1분 5초');
  expect(usage?.textContent).toContain('입력 1,240, 출력 680 토큰');
  expect(usage?.textContent).toContain('$0.01');
  expect(usage?.textContent).toContain('1개');
  expect(document.querySelector('[data-slot="result-facts"]')?.textContent).toContain('입력 1,240, 출력 680 토큰');
});

test('test_27_the_usage_button_closes_the_card_and_moves_to_the_usage_section', async () => {
  const onOpenEdit = vi.fn();
  renderExport(builtView(), stubApi(), { onOpenEdit });
  const card = await screen.findByRole('dialog', { name: '영상을 다 만들었어요' });

  fireEvent.click(within(card).getByRole('button', { name: '사용량 보기' }));

  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-slot="export-usage"]')));
  expect(onOpenEdit).not.toHaveBeenCalled();
});

test('test_27_the_credit_line_of_the_music_shows_next_to_the_video', async () => {
  renderExport(builtView(), stubApi());
  await closeCard();

  expect(document.querySelector('[data-slot="export-attribution"]')?.textContent).toContain('배경 음악: 합성 곡 (CC BY 4.0)');
});

test('test_13_saving_for_the_next_video_is_an_explicit_action_that_sends_only_the_video_and_a_name', async () => {
  const api = stubApi();
  const view = builtView();
  renderExport(view, api);
  await closeCard();
  expect(api.savePreset).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: '다음 영상도 이 설정으로' }));

  expect(await screen.findByText('다음 영상도 이 설정으로 시작해요.')).toBeTruthy();
  expect(api.savePreset).toHaveBeenCalledWith(view.video.project_id, {
    video_id: view.video.id,
    name: view.video.topic,
  });
});

test('test_13_a_failed_save_for_the_next_video_says_so_and_can_be_tried_again', async () => {
  const api = stubApi({ savePreset: vi.fn(async () => { throw new Error('offline'); }) });
  renderExport(builtView(), api);
  await closeCard();

  fireEvent.click(screen.getByRole('button', { name: '다음 영상도 이 설정으로' }));

  expect(await screen.findByText('저장하지 못했어요. 잠시 뒤에 다시 눌러 주세요.')).toBeTruthy();
  expect((screen.getByRole('button', { name: '다음 영상도 이 설정으로' }) as HTMLButtonElement).disabled).toBe(false);
});

test('test_10a_the_result_scenes_use_the_edit_scene_card_number_and_the_blue_dot', async () => {
  renderExport(builtView(), stubApi(), { unseen: ['s_0scene2000000000000000000'] });
  await closeCard();

  const rail = document.querySelector<HTMLElement>('[data-slot="export-scenes"]')!;
  const numbers = Array.from(rail.querySelectorAll('.card__number')).map((node) => `장면 ${node.textContent}`);
  expect(numbers).toEqual(SCENE_NUMBERS);
  const dots = rail.querySelectorAll('[data-slot="scene-unseen"]');
  expect(dots).toHaveLength(1);
  expect(dots[0]?.closest('[data-scene-id]')?.getAttribute('data-scene-id')).toBe('s_0scene2000000000000000000');
  expect(dots[0]?.className).toContain('size-[10px]');
});

test('test_19_pressing_a_result_scene_hands_that_scene_to_the_caller', async () => {
  const onPickScene = vi.fn();
  renderExport(builtView(), stubApi(), { onPickScene });
  await closeCard();

  fireEvent.click(screen.getByRole('button', { name: '첫 번째' }));

  expect(onPickScene).toHaveBeenCalledWith('s_0scene2000000000000000000');
});

test('test_10a_only_the_result_card_says_done_and_no_state_says_enlarge', async () => {
  const done = /다 만들었/u;
  const words = /크게 보기|이 영상으로 새 영상 만들기/u;
  renderExport(unbuiltView(), stubApi());
  await screen.findByText(REPORT.opening_promise);
  expect(document.body.textContent).not.toMatch(done);
  expect(document.body.textContent).not.toMatch(words);
  cleanup();
  configureExport(null);

  renderExport(builtView(), stubApi());
  const card = await screen.findByRole('dialog', { name: '영상을 다 만들었어요' });
  expect(card.textContent).not.toMatch(words);
  await closeCard();
  expect(document.body.textContent).not.toMatch(done);
  expect(document.body.textContent).not.toMatch(words);
});

test('test_30_a_started_making_is_not_started_again_when_the_screen_comes_back', async () => {
  const view = unbuiltView();
  view.video.material = [];
  const api = stubApi();
  const onStart = vi.fn(async () => true);
  renderExport(view, api, { onStart });
  await waitFor(() => expect(onStart).toHaveBeenCalledTimes(1));
  cleanup();

  // The screen mounts again on the same revision, as it does after the video is made.
  renderExport(view, api, { onStart, sameSession: true });
  await screen.findByRole('status');
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(onStart).toHaveBeenCalledTimes(1);
  cleanup();

  // A new confirmation in the edit step starts it once more.
  rearmAutoStart(view.video.id);
  renderExport(view, api, { onStart, sameSession: true });
  await waitFor(() => expect(onStart).toHaveBeenCalledTimes(2));
});
