import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { ExportRoute } from '@/app/routes/export';
import { PlaceholderComposer } from '@/app/shell/composer';
import { ShellViewProvider } from '@/app/shell/shell-view';
import { createMockEditApi } from '@/features/edit/api';
import { EditProvider } from '@/features/edit/edit-context';
import { ExportNextAction } from '@/features/export/next-action';
import { configureExport } from '@/features/export/store';
import { refreshSession, type Job } from '@/shared/api/client';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

import { DRAFT_VIDEO, DRAFT_VIDEO_PATH, draftJob, shellRoutes, stubApi as stubServer } from '../support/api';
import { renderApp, sendSentence } from '../support/render';

import { builtView, job, stubApi, unbuiltView } from './fixtures';

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  configureExport(null);
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.localStorage.clear();
});

test('test_19_the_result_composer_sends_to_the_selected_scene_without_leaving_export', async () => {
  configureExport(stubApi());
  const api = createMockEditApi(builtView());
  const send = vi.spyOn(api, 'sendMessage');
  const onStage = vi.fn();
  const videoId = 'v_test';
  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <EditProvider active videoId={videoId} api={api}>
        <ExportNextAction videoId={videoId} />
        <ExportRoute videoId={videoId} onStage={onStage} onSavePreset={() => undefined} />
        <ShellViewProvider value="export">
          <PlaceholderComposer label="편집 요청" placeholder="편집 요청" sendLabel="보내기" />
        </ShellViewProvider>
      </EditProvider>
    </LocaleProvider>,
  );

  fireEvent.click(await screen.findByRole('button', { name: '결과 카드 닫기' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.getAllByText('장면 1')[0]).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: '첫 번째' }));

  expect((await screen.findAllByText('장면 2'))[0]).toBeTruthy();
  fireEvent.change(screen.getByRole('textbox', { name: '편집 요청' }), { target: { value: '이 장면만 줄여 줘' } });
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  expect(send).toHaveBeenCalledWith(videoId, expect.objectContaining({
    text: '이 장면만 줄여 줘',
    target: { scene_id: 's_0scene2000000000000000000', pointer: null },
  }));
  expect(onStage).not.toHaveBeenCalled();
});

test('test_19b_a_change_that_needs_confirmation_moves_to_edit_where_it_can_be_decided', async () => {
  configureExport(stubApi());
  const view = builtView();
  const api = createMockEditApi(view);
  const originalSend = api.sendMessage.bind(api);
  const originalRead = api.readJob.bind(api);
  const results = new Map<string, Job>();
  api.sendMessage = async (videoId, body) => {
    const queued = await originalSend(videoId, body);
    const plan = await api.change(videoId, {
      base_revision: body.base_revision,
      source: 'direct',
      target: body.target,
      ops: [{ op: 'remove_scene', scene_id: view.video.scene_order[1] }],
    });
    results.set(queued.id, { ...queued, state: 'succeeded', result: { change_id: plan.id } });
    return queued;
  };
  api.readJob = async (id) => results.get(id) ?? originalRead(id);
  const onStage = vi.fn();
  const videoId = 'v_test';
  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <EditProvider active videoId={videoId} api={api}>
        <ExportRoute videoId={videoId} onStage={onStage} onSavePreset={() => undefined} />
        <ShellViewProvider value="export">
          <PlaceholderComposer label="편집 요청" placeholder="편집 요청" sendLabel="보내기" />
        </ShellViewProvider>
      </EditProvider>
    </LocaleProvider>,
  );

  fireEvent.click(await screen.findByRole('button', { name: '결과 카드 닫기' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  fireEvent.click(screen.getByRole('button', { name: '첫 번째' }));
  fireEvent.change(await screen.findByRole('textbox', { name: '편집 요청' }), { target: { value: '마지막 장면 삭제' } });
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));

  await waitFor(() => expect(onStage).toHaveBeenCalledWith('edit'), { timeout: 5000 });
});

test('test_13_the_next_video_uses_the_saved_preset_but_never_the_previous_topic_script_or_result', async () => {
  const prior = builtView();
  prior.video.id = DRAFT_VIDEO;
  const projectId = 'p_06pxfteaw88hs93kkckw5j51ng';
  prior.video.project_id = projectId;
  const next = unbuiltView();
  next.video.topic = '';
  next.video.script = null;
  next.video.scene_order = [];
  next.video.stage = 'draft';
  const presetId = 'ps_0test000000000000000000';
  const createPath = `/api/v1/projects/${projectId}/videos`;
  configureExport(stubApi({
    loadVideo: async (id) => id === DRAFT_VIDEO ? prior : next,
    savePreset: async () => ({ id: presetId, project_id: projectId }) as never,
  }));
  const api = await renderApp({
    ...shellRoutes(),
    [`POST ${createPath}`]: ({ body }) => ({
      status: 201,
      body: body && typeof body === 'object' && 'preset_id' in body && body.preset_id === null
        ? prior.video
        : next.video,
    }),
    [`GET ${DRAFT_VIDEO_PATH}`]: () => ({ status: 200, body: prior }),
    [`GET /api/v1/videos/${next.video.id}`]: () => ({ status: 200, body: next }),
    [`POST /api/v1/videos/${next.video.id}/draft`]: () => ({ status: 202, body: draftJob }),
  });
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });
  fireEvent.click(screen.getByRole('button', { name: '단계 열기' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '내보내기' }));
  fireEvent.click(await screen.findByRole('button', { name: '결과 카드 닫기' }));
  fireEvent.click(screen.getByRole('button', { name: '다음 영상도 이 설정으로' }));
  await screen.findByText('다음 영상도 이 설정으로 시작해요.');
  fireEvent.click(screen.getByRole('button', { name: '새로 만들기' }));

  const box = (await screen.findByRole('textbox', { name: '만들고 싶은 영상을 한 문장으로 적어 주세요' })) as HTMLTextAreaElement;
  expect(box.value).toBe('');
  sendSentence('종이비행기를 접는 법');
  await screen.findByRole('heading', { name: '컨셉' });
  expect(api.count('POST', '/api/v1/projects')).toBe(1);
  expect(api.calls.filter((call) => call.path === createPath && call.method === 'POST').at(-1)?.body)
    .toEqual({ preset_id: presetId, from_video_id: null });
  expect(api.calls.find((call) => call.path === `/api/v1/videos/${next.video.id}/draft`)?.body)
    .toEqual({ base_revision: next.video.revision, message: '종이비행기를 접는 법', card_id: null });

  fireEvent.click(screen.getByRole('button', { name: '단계 열기' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '내보내기' }));
  expect(await screen.findByRole('heading', { name: '아직 만든 영상이 없어요' })).toBeTruthy();
  expect(screen.queryByRole('dialog')).toBeNull();
  expect((screen.getByRole('button', { name: 'mp4 저장' }) as HTMLButtonElement).disabled).toBe(true);
});

test('test_27_retry_uses_the_retained_job_and_can_finish_before_the_stage_changes', async () => {
  const view = unbuiltView();
  const editedResult = builtView();
  const stopped = job('generate', 'failed');
  stopped.error = { stage: 'srt', scene_id: null, code: 'internal', retryable: true, detail: {} };
  let retried = false;
  const retryPath = `/api/v1/jobs/${stopped.id}/retry`;
  const http = stubServer({
    ...shellRoutes(),
    [`POST ${retryPath}`]: () => {
      retried = true;
      return { status: 202, body: { ...stopped, state: 'succeeded', attempt: 2, error: null } };
    },
  });
  await refreshSession();
  const editApi = createMockEditApi(view);
  const initialLoad = editApi.load.bind(editApi);
  editApi.load = async (id) => retried ? editedResult : initialLoad(id);
  configureExport(stubApi({ jobs: async () => [stopped] }));
  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <EditProvider active videoId={view.video.id} api={editApi}>
        <ExportRoute videoId={view.video.id} onStage={() => undefined} onSavePreset={() => undefined} />
      </EditProvider>
    </LocaleProvider>,
  );
  expect(await screen.findByText('멈춘 부분: 자막')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '실패한 부분 다시 시도' }));
  expect(await screen.findByRole('dialog', { name: '영상' })).toBeTruthy();
  expect(http.count('POST', retryPath)).toBe(1);
  expect(http.count('POST', `/api/v1/videos/${view.video.id}/generate`)).toBe(0);
});
