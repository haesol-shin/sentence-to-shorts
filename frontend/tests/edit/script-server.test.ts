import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { resetScriptSessions } from '@/features/script/store';
import type { components } from '@/shared/api/generated/openapi';

import { DRAFT_JOB_PATH, DRAFT_VIDEO, DRAFT_VIDEO_PATH, draftJob, shellRoutes, type Answer } from '../support/api';
import { renderApp, sendSentence } from '../support/render';
import { makeView } from './fixtures';

const CHANGE_ID = 'c_00000000000000000000000001';
const APPLY_PATH = `/api/v1/changes/${CHANGE_ID}/apply`;
const CONFIRM_PATH = `${DRAFT_VIDEO_PATH}/script/confirm`;

afterEach(() => {
  cleanup();
  resetScriptSessions();
  vi.unstubAllGlobals();
});

test('real Script waits for draft, saves edits, and enters Edit only after server confirmation', async () => {
  vi.stubEnv('VITE_API_MODE', 'server');
  let finishDraft!: (answer: Answer) => void;
  const draftReply = new Promise<Answer>((resolve) => { finishDraft = resolve; });
  const view = makeView();
  const initialOrder = view.video.scene_order;
  view.video = {
    ...view.video,
    id: DRAFT_VIDEO,
    revision: 2,
    stage: 'draft',
    settings: {
      ...view.video.settings,
      format: { ...view.video.settings.format, register: 'friendly', scene_count: initialOrder.length },
    },
  };
  let savedScript: components['schemas']['SetScriptOp'] | undefined;
  let confirmAttempts = 0;
  let finishConfirm!: (answer: Answer) => void;
  const confirmReply = new Promise<Answer>((resolve) => { finishConfirm = resolve; });
  const api = await renderApp({
    ...shellRoutes(),
    [`GET ${DRAFT_JOB_PATH}`]: () => draftReply,
    [`GET ${DRAFT_VIDEO_PATH}`]: () => ({ status: 200, body: view }),
    [`POST ${DRAFT_VIDEO_PATH}/changes`]: ({ body }) => {
      const request = body as components['schemas']['ChangeRequest'];
      expect(request.base_revision).toBe(2);
      expect(request.source).toBe('direct');
      savedScript = request.ops.find((op) => op.op === 'set_script');
      return { status: 200, body: { id: CHANGE_ID, status: 'proposed', requires_confirmation: true } };
    },
    [`POST ${APPLY_PATH}`]: ({ body }) => {
      expect(body).toEqual({ base_revision: 2 });
      if (savedScript === undefined) throw new Error('Missing planned script');
      view.video = {
        ...view.video,
        revision: 3,
        script: savedScript.script,
        scene_order: savedScript.scenes.map((scene) => scene.id),
        scenes: Object.fromEntries(savedScript.scenes.map((scene) => [scene.id, scene])),
      };
      throw new Error('Connection dropped after saving the change');
    },
    [`POST ${CONFIRM_PATH}`]: ({ body }) => {
      expect(body).toEqual({ base_revision: 3 });
      confirmAttempts += 1;
      if (confirmAttempts === 1) return { status: 503 };
      return confirmReply;
    },
  });

  const original = '커피를 고르는 세 가지 기준';
  const edited = '좋은 커피를 고르는 방법을 알아봐요.';
  sendSentence(original);
  await screen.findByRole('heading', { name: '컨셉' });
  fireEvent.click(screen.getByRole('button', { name: '단계 열기' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '대본' }));
  expect(screen.getByText('대본을 불러오는 중이에요.')).toBeTruthy();
  expect(api.count('GET', DRAFT_VIDEO_PATH)).toBe(0);

  await act(async () => finishDraft({ status: 200, body: {
    ...draftJob, state: 'succeeded', result: { status: 'applied', applied_revision: 2 },
  } }));
  fireEvent.change(await screen.findByDisplayValue(original), { target: { value: edited } });
  fireEvent.click(screen.getAllByRole('button', { name: '아래로 옮기기' })[0]);
  const next = screen.getByRole('button', { name: '이대로 영상 만들기' });
  fireEvent.click(next);

  const failure = '대본을 확인하지 못했어요. 다시 눌러 주세요.';
  await waitFor(() => expect(api.count('POST', APPLY_PATH)).toBe(1));
  expect(await screen.findByText(failure)).toBeTruthy();
  expect(document.querySelector('[data-slot="edit-stage"]')).toBeNull();
  expect(api.count('POST', CONFIRM_PATH)).toBe(0);
  expect(savedScript?.script).toMatchObject({ raw_text: original, source: 'user' });
  expect(savedScript?.scenes.map((scene) => scene.id)).toEqual([
    initialOrder[1], initialOrder[0], initialOrder[2],
  ]);
  expect(savedScript?.scenes[1].lines[0]).toMatchObject({ display_text: edited, speech_text: edited });

  // Retry: the lost apply response is recovered from the head, not saved twice.
  fireEvent.click(next);
  await waitFor(() => expect(api.count('POST', CONFIRM_PATH)).toBe(1));
  await waitFor(() => expect((next as HTMLButtonElement).disabled).toBe(false));
  expect(await screen.findByText(failure)).toBeTruthy();
  expect(screen.getByDisplayValue(edited)).toBeTruthy();
  expect(document.querySelector('[data-slot="edit-stage"]')).toBeNull();
  expect(api.count('POST', `${DRAFT_VIDEO_PATH}/changes`)).toBe(1);
  expect(api.count('POST', APPLY_PATH)).toBe(1);

  fireEvent.click(next);
  await waitFor(() => expect(api.count('POST', CONFIRM_PATH)).toBe(2));
  expect(document.querySelector('[data-slot="edit-stage"]')).toBeNull();
  expect(api.count('POST', `${DRAFT_VIDEO_PATH}/previews`)).toBe(0);

  await act(async () => {
    view.video = { ...view.video, revision: 4, stage: 'script_confirmed' };
    finishConfirm({ status: 200, body: view.video });
  });
  await waitFor(() => expect(document.querySelector('[data-slot="edit-stage"]')).not.toBeNull());
  const generate = document.querySelector<HTMLButtonElement>('[data-slot="next-action"]');
  await waitFor(() => expect(generate?.disabled).toBe(false));
  expect(api.count('POST', `${DRAFT_VIDEO_PATH}/changes`)).toBe(1);
  vi.unstubAllEnvs();
});
