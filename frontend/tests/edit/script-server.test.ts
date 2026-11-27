import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { openServerScript } from '@/features/script/server-script';
import { confirmScript, ensureScript, getScriptSnapshot, resetScriptSessions, syncScriptSettings } from '@/features/script/store';
import { pairSession } from '@/shared/api/client';
import type { components } from '@/shared/api/generated/openapi';

import { DRAFT_JOB_PATH, DRAFT_VIDEO, DRAFT_VIDEO_PATH, draftJob, shellRoutes, stubApi, type Answer } from '../support/api';
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
  const conceptConfirm = document.querySelector<HTMLButtonElement>('.concept-footer button:last-child');
  expect(conceptConfirm?.disabled).toBe(true);
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

test('test_8a_scene_message_uses_the_saved_draft_but_keeps_the_rewrite_proposed', async () => {
  vi.stubEnv('VITE_API_MODE', 'server');
  const view = makeView();
  const [sceneId, otherId] = view.video.scene_order;
  const original = '커피를 고르는 세 가지 기준';
  const draftLine = '직접 쓴 문장을 더 간결하게 고쳐요.';
  const otherLine = '이 장면의 편집은 그대로 둬요.';
  const updated = '직접 쓴 문장을 고쳐요.';
  const job = { ...draftJob, id: 'j_00000000000000000000000002', kind: 'chat', state: 'succeeded', result: { change_id: CHANGE_ID } };
  const changePath = `/api/v1/changes/${CHANGE_ID}`;
  view.video = { ...view.video, id: DRAFT_VIDEO, stage: 'concept_confirmed' };
  const api = await renderApp({
    ...shellRoutes(),
    [`GET ${DRAFT_JOB_PATH}`]: () => ({ status: 200, body: { ...draftJob, state: 'succeeded', result: { status: 'applied' } } }),
    [`GET ${DRAFT_VIDEO_PATH}`]: () => ({ status: 200, body: view }),
    [`POST ${DRAFT_VIDEO_PATH}/changes`]: ({ body }) => {
      const request = body as components['schemas']['ChangeRequest'];
      const op = request.ops.find((item) => item.op === 'set_script');
      if (op === undefined) throw new Error('The draft was not saved');
      view.video = {
        ...view.video, revision: view.video.revision + 1, script: op.script,
        scenes: Object.fromEntries(op.scenes.map((scene) => [scene.id, scene])),
      };
      return { status: 200, body: { status: 'applied', applied_revision: view.video.revision } };
    },
    [`POST ${DRAFT_VIDEO_PATH}/messages`]: ({ body }) => {
      expect(body).toEqual({
        base_revision: view.video.revision, text: '더 짧게',
        target: { scene_id: sceneId, pointer: `/scenes/${sceneId}/lines` },
      });
      expect(view.video.scenes[sceneId].lines[0].display_text).toBe(draftLine);
      expect(view.video.scenes[otherId].lines[0].display_text).toBe(otherLine);
      return { status: 202, body: job };
    },
    [`GET ${changePath}`]: () => ({
      status: 200,
      body: {
        id: CHANGE_ID, status: 'proposed',
        ops: [
          { op: 'set', path: `/scenes/${sceneId}/lines`, value: [
            { ...view.video.scenes[sceneId].lines[0], display_text: updated, speech_text: updated },
          ] },
          { op: 'set', path: `/scenes/${sceneId}/beat_label`, value: '새 제목' },
        ],
        notes: ['제목은 편집 단계에서 바꿔요.'],
        unsupported: ['장면 순서는 대화에서 바꿀 수 없어요. 장면 카드를 끌어 주세요.'],
      },
    }),
    [`POST ${changePath}/reject`]: () => ({ status: 200 }),
  });
  sendSentence(original);
  await screen.findByRole('heading', { name: '컨셉' });
  fireEvent.click(screen.getByRole('button', { name: '단계 열기' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '대본' }));
  fireEvent.change(await screen.findByDisplayValue(original), { target: { value: draftLine } });
  const otherInput = document.querySelector(`[data-scene-id="${otherId}"] [data-slot="script-line-input"]`);
  if (otherInput === null) throw new Error('The other scene is missing');
  fireEvent.change(otherInput, { target: { value: otherLine } });
  fireEvent.click(screen.getByRole('button', { name: '장면 1 메뉴' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '이 장면을 대화로 고치기' }));
  const composer = screen.getAllByRole('textbox', { name: '고칠 점을 적어 주세요' })[0];
  fireEvent.change(composer, { target: { value: '더 짧게' } });
  fireEvent.keyDown(composer, { key: 'Enter' });

  expect(await screen.findByText(updated)).toBeTruthy();
  expect(screen.getAllByText(/장면 카드를 끌어 주세요/u).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/제목은 편집 단계에서 바꿔요/u).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/장면 제목과 효과음 변경은 대본에서 적용하지 않아요/u).length).toBeGreaterThan(0);
  expect(view.video.scenes[sceneId].lines[0].display_text).toBe(draftLine);
  expect(api.count('POST', APPLY_PATH)).toBe(0);
  fireEvent.click(screen.getByRole('button', { name: /^적용$/u }));
  expect(screen.getByDisplayValue(updated)).toBeTruthy();
  expect(screen.getByDisplayValue(otherLine)).toBeTruthy();
  vi.unstubAllEnvs();
});

test('test_8a_a_setting_changed_by_chat_is_adopted_without_losing_unsaved_lines', async () => {
  const view = makeView();
  view.video = {
    ...view.video, id: DRAFT_VIDEO,
    settings: { ...view.video.settings, format: { ...view.video.settings.format, register: 'friendly' } },
  };
  stubApi({ ...shellRoutes(), [`GET ${DRAFT_VIDEO_PATH}`]: () => ({ status: 200, body: view }) });
  const { document, sync } = await openServerScript(DRAFT_VIDEO, { id: DRAFT_VIDEO, topic: null, script: null });
  const sceneId = document.scene_order[0];
  const typed = { ...document, scenes: { ...document.scenes, [sceneId]: {
    ...document.scenes[sceneId],
    lines: [{ ...document.scenes[sceneId].lines[0], display_text: '아직 저장하지 않은 줄', speech_text: '아직 저장하지 않은 줄' }],
  } } };

  view.video = {
    ...view.video, revision: view.video.revision + 1,
    settings: {
      ...view.video.settings,
      target_duration_s: 60,
      format: { ...view.video.settings.format, register: 'casual', scene_count: view.video.scene_order.length + 3 },
    },
  };
  const synced = await sync(typed);

  expect(synced.register).toBe('casual');
  expect(synced.target_duration_s).toBe(60);
  expect(synced.scenes[sceneId].lines[0].display_text).toBe('아직 저장하지 않은 줄');
});

test('test_8a_settings_applied_after_a_pending_chat_plan_do_not_block_confirm', async () => {
  const view = makeView();
  view.video = {
    ...view.video, id: DRAFT_VIDEO, revision: 2, stage: 'concept_confirmed',
    settings: { ...view.video.settings, format: { ...view.video.settings.format, register: 'friendly' } },
  };
  let confirms = 0;
  stubApi({
    ...shellRoutes(),
    [`GET ${DRAFT_VIDEO_PATH}`]: () => ({ status: 200, body: view }),
    [`POST ${CONFIRM_PATH}`]: ({ body }) => {
      confirms += 1;
      expect(body).toEqual({ base_revision: view.video.revision });
      return { status: 200, body: { ...view.video, stage: 'script_confirmed', revision: view.video.revision + 1 } };
    },
  });
  await pairSession('000000');
  await ensureScript('ko', { id: `${DRAFT_VIDEO}#1`, topic: null, script: null }, DRAFT_VIDEO);
  await syncScriptSettings(5);

  // The plan was pending when the first read ran; applying it moves the concept revision later.
  view.video = {
    ...view.video, revision: 3,
    settings: { ...view.video.settings, format: { ...view.video.settings.format, register: 'casual' } },
  };
  await syncScriptSettings(6);

  expect(getScriptSnapshot()?.document.register).toBe('casual');
  expect(await confirmScript()).toBe(true);
  expect(confirms).toBe(1);
});
