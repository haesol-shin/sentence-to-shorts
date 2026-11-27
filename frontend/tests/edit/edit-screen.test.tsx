import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, expect, test } from 'vitest';

import { HistoryButtons } from '@/app/shell/history-buttons';
import { PlaceholderComposer } from '@/app/shell/composer';
import { ShellViewProvider } from '@/app/shell/shell-view';
import { createMockEditApi, stageRecord, type Job } from '@/features/edit/api';
import { EditChatHistory } from '@/features/edit/chat-history';
import { EditProvider, useEdit } from '@/features/edit/edit-context';
import { EditScreen } from '@/features/edit/edit-screen';
import { EditNextAction } from '@/features/edit/next-action';
import { clearSceneConfirmRequest, requestSceneConfirm } from '@/features/edit/scene-confirm-request';
import { StillBuild } from '@/features/edit/still-build';
import { EditTopBarStatus } from '@/features/edit/top-bar-status';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

import { makeView } from './fixtures';

afterEach(() => {
  cleanup();
  clearSceneConfirmRequest();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

const view = makeView();

function wrap(children: ReactNode, api = createMockEditApi(view), language: 'ko' | 'en' = 'ko') {
  return render(
    <LocaleProvider language={language} setLanguage={() => undefined}>
      <EditProvider active videoId="v_test" api={api}>
        <HistoryButtons view="edit" />
        {children}
      </EditProvider>
    </LocaleProvider>,
  );
}

async function renderScreen() {
  wrap(<EditScreen />);
  await screen.findByRole('heading', { name: '장면 1' });
  return document.querySelector<HTMLElement>('[data-slot="scene-column"]') as HTMLElement;
}

function EditActions() {
  const edit = useEdit();
  return (
    <>
      <EditNextAction />
      {edit.confirmedForOutput && edit.video !== null ? (
        <button onClick={() => {
          const revision = edit.video?.revision;
          if (revision === undefined) return;
          edit.acknowledgeOutput();
          void edit.generateVideo(revision);
        }}>확인 후 생성</button>
      ) : null}
      <EditTopBarStatus />
      <StillBuild edit={edit} />
    </>
  );
}

function openComposer(api = createMockEditApi(view), children?: ReactNode, language: 'ko' | 'en' = 'ko') {
  return wrap(
    <ShellViewProvider value="edit">
      <div className="flex h-96 flex-col">
        <EditChatHistory />
        <PlaceholderComposer label="편집 요청" placeholder="편집 요청" sendLabel="보내기" />
      </div>
      {children}
    </ShellViewProvider>,
    api,
    language,
  );
}

async function startVideo() {
  const action = await screen.findByRole('button', { name: '영상 만들기' });
  await waitFor(() => expect((action as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(action);
  fireEvent.click(
    within(screen.getByRole('dialog', { name: '장면 확인' })).getByRole('button', {
      name: '영상 만들기',
    }),
  );
}

test('test_10a_the_edit_screen_lists_the_scene_cards', async () => {
  const column = await renderScreen();
  expect(column.querySelectorAll('[data-slot="scene-card"]')).toHaveLength(3);
  expect(column.querySelector('[data-slot="scene-still"]')).not.toBeNull();
  expect(screen.getByRole('heading', { name: '미리보기' })).toBeTruthy();
  expect(screen.getAllByText('첫 줄').length).toBeGreaterThan(0);
});

function positionField() {
  return screen.getByRole<HTMLButtonElement>('combobox', { name: '위치' });
}

async function choosePosition(name: string) {
  fireEvent.click(positionField());
  const option = await screen.findByRole('option', { name });
  fireEvent.pointerDown(option);
  fireEvent.pointerUp(option);
  fireEvent.mouseUp(option);
  fireEvent.click(option);
}

test('test_23_the_position_menu_shows_nine_places_and_undoes', async () => {
  await renderScreen();
  expect(positionField().textContent).toContain('가운데 아래');
  fireEvent.click(positionField());
  expect(await screen.findAllByRole('option')).toHaveLength(9);
  fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });

  await choosePosition('왼쪽 위');
  await waitFor(() => expect(positionField().textContent).toContain('왼쪽 위'));
  await waitFor(() => expect((screen.getByRole('button', { name: '되돌리기' }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: '되돌리기' }));
  await waitFor(() => expect(positionField().textContent).toContain('가운데 아래'));
});

test('test_23_undo_applies_only_once', async () => {
  await renderScreen();
  const undo = screen.getByRole('button', { name: '되돌리기' }) as HTMLButtonElement;
  expect(undo.disabled).toBe(true);
  await choosePosition('왼쪽 위');
  await waitFor(() => expect(undo.disabled).toBe(false));
  fireEvent.click(undo);
  await waitFor(() => expect(undo.disabled).toBe(true));
  expect(positionField().textContent).toContain('가운데 아래');
});

test('test_23_a_current_scene_change_does_not_leave_an_unseen_dot', async () => {
  const column = await renderScreen();
  await choosePosition('왼쪽 위');
  await waitFor(() => expect(column.querySelectorAll('[data-slot="scene-unseen"]')).toHaveLength(0));
});

test('test_23_the_position_change_invalidates_the_still', async () => {
  await renderScreen();
  const picture = screen.getByRole('img', { name: '장면 1 정지 그림, 훅' });
  const caption = document.querySelector('[data-slot="preview-caption"]');
  expect(caption?.textContent).toBe('첫 줄');
  expect(picture.contains(caption)).toBe(false);
  await choosePosition('왼쪽 위');
  await waitFor(() => expect(screen.queryByRole('img', { name: '장면 1 정지 그림, 훅' })).toBeNull());
  const note = await screen.findByText('장면 그림이 아직 없어요.', { selector: '[role="status"]' });
  expect(note.closest('[role="img"]')).toBeNull();
});

test('test_10a_the_english_edit_screen_names_its_jump_control_in_english', async () => {
  wrap(<EditScreen />, createMockEditApi(view), 'en');
  await screen.findByRole('heading', { name: 'Scene 1' });

  const scenes = screen.getByRole('region', { name: 'Scenes' });
  for (const [name, value] of Object.entries({ scrollHeight: 1000, clientHeight: 400, scrollTop: 0 })) {
    Object.defineProperty(scenes, name, { configurable: true, value });
  }
  fireEvent.scroll(scenes);
  expect(within(scenes.parentElement as HTMLElement).getByRole('button', { name: 'Scroll down' })).toBeTruthy();
});

test('test_23_adding_a_scene_asks_for_the_server_rebuild_scope', async () => {
  const api = createMockEditApi(view);
  const first = wrap(<EditScreen />, api);
  await screen.findByRole('heading', { name: '장면 1' });
  const column = document.querySelector<HTMLElement>('[data-slot="scene-column"]')!;
  fireEvent.click(within(column).getByRole('button', { name: '장면 추가' }));
  const dialog = await screen.findByRole('dialog', { name: '장면을 추가할까요?' });
  expect(within(dialog).getByText('다시 만들 범위')).toBeTruthy();
  expect(dialog.querySelector('[data-slot="text-compare"]')).not.toBeNull();
  expect(within(dialog).getByText('장면 1 복제본을 지금 장면 뒤에 넣어요.')).toBeTruthy();
  expect(dialog.querySelector('[data-slot="rebuild-scope"]')?.textContent).toContain('2. 훅');
  expect(dialog.textContent).not.toMatch(/\bs_[0-9a-z]{6,}/u);
  await waitFor(() => expect(dialog.querySelector('[data-slot="preview-after"]')).not.toBeNull());
  const previewImage = dialog.querySelector<HTMLImageElement>('img[data-slot="preview-after"]');
  expect(previewImage?.src.startsWith('data:image/png')).toBe(true);
  const apply = within(dialog).getByRole('button', { name: '적용' });
  expect(apply).toHaveProperty('disabled', true);
  fireEvent.load(previewImage!);
  fireEvent.click(apply);
  await waitFor(() => expect(column.querySelectorAll('[data-slot="scene-card"]')).toHaveLength(4));
  expect(await screen.findByRole('heading', { name: '장면 2' })).toBeTruthy();
  first.unmount();
  wrap(<EditScreen />, api);
  expect(await screen.findByRole('heading', { name: '장면 2' })).toBeTruthy();
});

test.each(['image', 'job'] as const)('test_23_a_failed_%s_cannot_bypass_change_comparison', async (failure) => {
  const api = createMockEditApi(view);
  const originalPreview = api.previewChange.bind(api);
  if (failure === 'job') {
    api.previewChange = async (id) => ({ ...await originalPreview(id), state: 'failed', result: null });
  }
  wrap(<EditScreen />, api);
  await screen.findByRole('heading', { name: '장면 1' });
  const column = document.querySelector<HTMLElement>('[data-slot="scene-column"]')!;
  fireEvent.click(within(column).getByRole('button', { name: '장면 추가' }));
  const dialog = await screen.findByRole('dialog', { name: '장면을 추가할까요?' });
  if (failure === 'image') {
    const image = await waitFor(() => {
      const node = dialog.querySelector('[data-slot="preview-after"]');
      expect(node).not.toBeNull();
      return node!;
    });
    fireEvent.error(image);
  }
  await within(dialog).findByText('미리보기를 만들지 못했어요.');
  expect(within(dialog).getByRole('button', { name: '적용' })).toHaveProperty('disabled', true);
  fireEvent.click(within(dialog).getByRole('button', { name: '취소' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(column.querySelectorAll('[data-slot="scene-card"]')).toHaveLength(3);
});

test('test_23_the_order_warning_precedes_even_an_auto_applied_server_change', async () => {
  const api = createMockEditApi(view);
  const originalChange = api.change.bind(api);
  const savedOrders: string[][] = [];
  api.change = async (id, body) => {
    for (const op of body.ops) if (op.op === 'reorder') savedOrders.push(op.order);
    return originalChange(id, body);
  };
  wrap(<EditScreen />, api);
  await screen.findByRole('heading', { name: '장면 1' });
  // The scene column is where the edit step reorders; the first card is dropped on the second.
  const second = document.querySelectorAll<HTMLElement>('[data-slot="scene-column"] [data-slot="scene-card"]')[1]!;
  fireEvent.drop(second, { dataTransfer: { getData: () => view.video.scene_order[0] } });
  const dialog = await screen.findByRole('dialog', { name: '장면 순서를 바꿀까요?' });
  expect(within(dialog).getByText('장면 흐름이 끊길 수 있어요. 순서를 한 번 더 확인해 주세요.')).toBeTruthy();
  expect(savedOrders).toEqual([]);
  fireEvent.click(within(dialog).getByRole('button', { name: '적용' }));
  await waitFor(() => expect(savedOrders).toEqual([[view.video.scene_order[1], view.video.scene_order[0], view.video.scene_order[2]]]));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

test('test_26_the_edit_scene_panel_has_no_add_line_control', async () => {
  await renderScreen();
  expect(screen.queryByRole('button', { name: '대사 줄 추가' })).toBeNull();
  expect(document.querySelector('[data-slot="line-draft"]')).toBeNull();
});

test('test_23_deleting_a_scene_asks_first_and_can_be_kept', async () => {
  const column = await renderScreen();
  fireEvent.click(screen.getByRole('button', { name: '장면 삭제' }));
  const dialog = await screen.findByRole('dialog', { name: '장면을 삭제할까요?' });
  fireEvent.click(within(dialog).getByRole('button', { name: '취소' }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '장면을 삭제할까요?' })).toBeNull());
  expect(column.querySelectorAll('[data-slot="scene-card"]')).toHaveLength(3);

  fireEvent.click(screen.getByRole('button', { name: '장면 삭제' }));
  const second = await screen.findByRole('dialog', { name: '장면을 삭제할까요?' });
  expect(within(second).getByText('삭제될 장면')).toBeTruthy();
  fireEvent.click(within(second).getByRole('button', { name: '적용' }));
  await waitFor(() => expect(column.querySelectorAll('[data-slot="scene-card"]')).toHaveLength(2));
});

test('test_10a_the_preview_advances_the_last_line_and_stops_at_the_end', async () => {
  await renderScreen();
  const preview = within(document.querySelector('[data-slot="preview"]') as HTMLElement);
  expect(preview.getAllByText('첫 줄')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: '재생' }));
  expect(await preview.findByText('둘째 줄', {}, { timeout: 2500 })).toBeTruthy();
  expect(preview.queryByText('첫 줄')).toBeNull();
  await waitFor(() => expect(screen.getByRole('button', { name: '재생' })).toBeTruthy(), {
    timeout: 3500,
  });
});

test('test_10a_the_scene_picture_build_modal_blocks_and_only_cancels', async () => {
  const scriptView = makeView();
  scriptView.video.stage = 'script_confirmed';
  wrap(<><EditScreen /><EditNextAction /></>, createMockEditApi(scriptView));
  await startVideo();
  const stills = await screen.findByRole('dialog', { name: '장면 그림을 만들고 있어요' });
  expect(within(stills).getByRole('button', { name: '작업 취소' })).toBeTruthy();
  expect(within(stills).queryByRole('button', { name: '닫기' })).toBeNull();
  expect(document.querySelectorAll('[data-slot="scene-column"] [data-busy]')).toHaveLength(3);
  expect(await within(stills).findByText('1 / 3')).toBeTruthy();
  fireEvent.click(within(stills).getByRole('button', { name: '작업 취소' }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '장면 그림을 만들고 있어요' })).toBeNull());
});

test('test_10a_script_confirmed_previews_and_waits_for_output_confirmation_to_generate', async () => {
  const scriptView = makeView();
  scriptView.video.stage = 'script_confirmed';
  wrap(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <EditProvider active videoId="v_test" api={createMockEditApi(scriptView)}>
        <EditActions />
      </EditProvider>
    </LocaleProvider>,
  );
  await startVideo();
  expect(await screen.findByRole('dialog', { name: '장면 그림을 만들고 있어요' })).toBeTruthy();
  expect(await within(screen.getByRole('dialog', { name: '장면 그림을 만들고 있어요' })).findByText('1 / 3')).toBeTruthy();
  const confirmed = await screen.findByRole('button', { name: '확인 후 생성' });
  expect(screen.queryByRole('button', { name: /영상 만드는 중/u })).toBeNull();
  fireEvent.click(confirmed);
  expect(await screen.findByRole('button', { name: '영상 만드는 중 1 / 3' }, { timeout: 6000 })).toBeTruthy();
  expect(screen.queryByRole('dialog', { name: '장면 그림을 만들고 있어요' })).toBeNull();
});

test('test_10a_a_comparison_preview_is_not_resumed_as_scene_picture_work', async () => {
  const scriptView = makeView();
  scriptView.video.stage = 'script_confirmed';
  const api = createMockEditApi(scriptView);
  const originalLoad = api.load.bind(api);
  api.load = async (videoId) => {
    const view = await originalLoad(videoId);
    view.open_jobs = ['j_compare'];
    return view;
  };
  api.readJob = async () => ({
    id: 'j_compare',
    kind: 'preview',
    state: 'running',
    stages: [],
    checkpoints: [],
  } as unknown as Job);
  const calls: string[] = [];
  api.confirmScenes = async () => {
    calls.push('confirm');
    return scriptView.video;
  };
  api.generate = async () => {
    calls.push('generate');
    return {} as Job;
  };
  wrap(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <EditProvider active videoId="v_test" api={api}>
        <EditActions />
      </EditProvider>
    </LocaleProvider>,
  );
  await screen.findByRole('button', { name: '영상 만들기' });
  await new Promise((resolve) => setTimeout(resolve, 700));
  expect(calls).toEqual([]);
});

test('test_10a_the_progress_window_has_no_stop_control', async () => {
  const api = createMockEditApi(view);
  const originalGenerate = api.generate.bind(api);
  api.generate = async (id, revision) => {
    const job = await originalGenerate(id, revision);
    const started = { ...job, stages: [stageRecord('clip', 'running')] };
    api.readJob = async () => started;
    return started;
  };
  wrap(<EditActions />, api);
  await startVideo();
  fireEvent.click(await screen.findByRole('button', { name: '확인 후 생성' }));
  const status = await screen.findByRole('button', { name: /영상 만드는 중/ }, { timeout: 5000 });
  fireEvent.click(status);
  const dialog = await screen.findByRole('dialog', { name: '영상을 만들고 있어요' });
  expect(status.textContent).toContain('0 / 3');
  const scenes = dialog.querySelectorAll('[data-slot="progress-scene"]');
  expect([...scenes].map((scene) => scene.getAttribute('data-state'))).toEqual(['running', 'waiting', 'waiting']);
  expect(within(dialog).getAllByRole('button')).toHaveLength(1);
  expect(within(dialog).getByRole('button', { name: /닫기/ })).toBeTruthy();
});

test('test_10a_the_top_bar_stop_works_while_the_progress_window_is_open', async () => {
  wrap(<EditActions />);
  await startVideo();
  fireEvent.click(await screen.findByRole('button', { name: '확인 후 생성' }));
  const status = await screen.findByRole('button', { name: /영상 만드는 중/ }, { timeout: 5000 });
  fireEvent.click(status);
  const dialog = await screen.findByRole('dialog', { name: '영상을 만들고 있어요' });
  expect(dialog).toBeTruthy();
  const stop = screen.getByRole('button', { name: /만들기 멈추기/ });
  fireEvent.click(stop);
  await waitFor(() => expect(screen.getByRole('button', { name: '영상 만들기' })).toBeTruthy());
});

test('test_23_the_sfx_picker_uses_catalog_references', async () => {
  await renderScreen();
  fireEvent.click(screen.getByRole('button', { name: '효과음 추가' }));
  const picker = await screen.findByRole('dialog', { name: '효과음 추가' });
  fireEvent.click(within(picker).getByRole('button', { name: '팝' }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '효과음 추가' })).toBeNull());
  fireEvent.click(screen.getByRole('button', { name: '효과음 추가' }));
  const second = await screen.findByRole('dialog', { name: '효과음 추가' });
  fireEvent.click(within(second).getByRole('button', { name: '휙' }));
  await waitFor(() => expect((screen.getByRole('button', { name: '효과음 추가' }) as HTMLButtonElement).disabled).toBe(true));
});

test('test_26_a_line_has_one_caption_box_and_the_voice_follows_it', async () => {
  const api = createMockEditApi(view);
  wrap(<EditScreen />, api);
  await screen.findByRole('heading', { name: '장면 1' });
  const display = screen.getByRole('textbox', { name: '화면 글 1' }) as HTMLTextAreaElement;
  expect(screen.queryByRole('textbox', { name: /말할 글/ })).toBeNull();
  fireEvent.change(display, { target: { value: '고친 첫 줄' } });
  fireEvent.click(within(display.closest('[data-slot="line-editor"]') as HTMLElement).getByRole('button', { name: '줄 저장' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '되돌리기' })).toHaveProperty('disabled', false));
  expect(display.value).toBe('고친 첫 줄');
  const saved = (await api.load('v_test')).video.scenes[view.video.scene_order[0] ?? '']?.lines[0];
  expect(saved?.display_text).toBe('고친 첫 줄');
  expect(saved?.speech_text).toBe('고친 첫 줄');
});

test('test_10a_the_edit_composer_targets_a_scene_and_sends', async () => {
  openComposer();
  await screen.findByRole('textbox', { name: '편집 요청' });
  const target = screen.getAllByText('장면 1')[0];
  expect(target).toBeTruthy();
  const input = screen.getByRole('textbox', { name: '편집 요청' }) as HTMLTextAreaElement;
  expect(input.disabled).toBe(false);
  expect(input.placeholder).toMatch(/더 짧게/u);
  fireEvent.change(input, { target: { value: '이 장면을 더 짧게' } });
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  expect(await screen.findByText('바꿀 값이 없어요.', {}, { timeout: 3000 })).toBeTruthy();
  expect(screen.getByText('이 장면을 더 짧게')).toBeTruthy();
});

test.each([
  { language: 'ko', stopName: '요청 멈추기', cancellation: '요청을 멈췄어요.' },
  { language: 'en', stopName: 'Stop the request', cancellation: 'The request was stopped.' },
] as const)('test_10a_a_chat_request_can_be_stopped_in_$language_and_keeps_the_composer_open', async ({
  language, stopName, cancellation,
}) => {
  openComposer(undefined, undefined, language);
  await screen.findByRole('textbox', { name: '편집 요청' });
  const input = screen.getByRole('textbox', { name: '편집 요청' });
  fireEvent.change(input, { target: { value: '이 장면을 더 짧게' } });
  const send = screen.getByRole('button', { name: '보내기' }) as HTMLButtonElement;
  await waitFor(() => expect(send.disabled).toBe(false));
  fireEvent.click(send);
  const stop = await screen.findByRole('button', { name: stopName });
  expect((input as HTMLTextAreaElement).disabled).toBe(false);
  fireEvent.click(stop);
  await waitFor(() => expect(screen.getByRole('button', { name: '보내기' })).toBeTruthy());
  expect((screen.getByRole('textbox', { name: '편집 요청' }) as HTMLTextAreaElement).disabled).toBe(false);
  expect(await screen.findByText(cancellation)).toBeTruthy();
});

test('test_10a_a_message_sent_while_chat_waits_runs_after_it', async () => {
  openComposer();
  await screen.findAllByText('장면 1');
  const input = screen.getByRole('textbox', { name: '편집 요청' }) as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: '첫 요청' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  await screen.findByRole('button', { name: '요청 멈추기' });
  fireEvent.change(input, { target: { value: '둘째 요청' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(await screen.findByText('둘째 요청')).toBeTruthy();
  await waitFor(() => expect(screen.getAllByText('바꿀 값이 없어요.').length).toBeGreaterThanOrEqual(2), { timeout: 5000 });
  expect((screen.getByRole('textbox', { name: '편집 요청' }) as HTMLTextAreaElement).disabled).toBe(false);
});

test('test_10a_stopping_a_later_post_cancels_that_job_and_discards_only_the_waiting_requests', async () => {
  const api = createMockEditApi(view);
  const originalSend = api.sendMessage.bind(api);
  const originalCancel = api.cancelJob.bind(api);
  const sent: string[] = [];
  const cancelled: string[] = [];
  let releaseSecond!: () => void;
  const secondResponse = new Promise<void>((resolve) => { releaseSecond = resolve; });
  let secondJob: Job | undefined;
  api.sendMessage = async (videoId, body) => {
    sent.push(body.text);
    const job = await originalSend(videoId, body);
    if (body.text !== '둘째 요청') return job;
    secondJob = job;
    await secondResponse;
    return job;
  };
  api.cancelJob = async (id) => {
    cancelled.push(id);
    const job = await originalCancel(id);
    return { ...job, state: 'cancelling' };
  };

  openComposer(api);
  await screen.findAllByText('장면 1');
  const input = screen.getByRole('textbox', { name: '편집 요청' });
  const send = (message: string) => {
    fireEvent.change(input, { target: { value: message } });
    fireEvent.keyDown(input, { key: 'Enter' });
  };
  send('첫 요청');
  await screen.findByRole('button', { name: '요청 멈추기' });
  send('둘째 요청');
  await waitFor(() => expect(secondJob).toBeDefined());
  send('버릴 요청');
  fireEvent.click(screen.getByRole('button', { name: '요청 멈추기' }));
  expect(await screen.findByText('대기 중이던 요청은 보내지 않았어요.')).toBeTruthy();
  expect(cancelled).toEqual([]);
  expect(input).toHaveProperty('disabled', false);
  releaseSecond();

  expect(await screen.findByText('요청을 멈췄어요.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '요청 멈추기' })).toBeNull();
  expect(cancelled).toEqual([secondJob!.id]);
  send('멈춘 뒤 새 요청');
  await waitFor(() => expect(screen.getAllByText('바꿀 값이 없어요.')).toHaveLength(2));
  expect(sent).toEqual(['첫 요청', '둘째 요청', '멈춘 뒤 새 요청']);
});

test('test_10a_scene_chat_uses_the_change_and_reports_unsupported_parts_of_the_same_result', async () => {
  const api = createMockEditApi(view);
  const originalSend = api.sendMessage.bind(api);
  let target: string | null = null;
  api.sendMessage = async (videoId, body) => {
    target = body.target.scene_id;
    const job = await originalSend(videoId, body);
    const plan = await api.change(videoId, {
      base_revision: body.base_revision,
      source: 'direct',
      target: body.target,
      ops: [{ op: 'set', path: `/scenes/${target}/beat_label`, value: '새 진행 제목', origin: 'user' }],
    });
    return { ...job, state: 'succeeded', result: {
      change_id: plan.id,
      unsupported: ['영상 언어는 장면 대화에서 바꿀 수 없어요. 첫 화면에서 영상 언어를 선택해 주세요.'],
    } };
  };
  openComposer(api);
  await screen.findAllByText('장면 1');
  fireEvent.change(screen.getByRole('textbox', { name: '편집 요청' }), { target: { value: '진행 제목과 영상 언어를 바꿔 주세요.' } });
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));

  expect(await screen.findByText('장면을 바꿨어요.')).toBeTruthy();
  expect(await screen.findByText(/첫 화면에서 영상 언어를 선택해 주세요/u)).toBeTruthy();
  expect(screen.queryByRole('button', { name: '요청 멈추기' })).toBeNull();
  expect(target).toBe(view.video.scene_order[0]);
});

test.each(['적용', '취소'])('test_10a_queued_chat_waits_for_the_first_proposal_to_be_decided_with_%s', async (decision) => {
  const api = createMockEditApi(view);
  const originalSend = api.sendMessage.bind(api);
  const firstResult = new Map<string, Job>();
  const sentRevisions: number[] = [];
  const originalRead = api.readJob.bind(api);
  api.sendMessage = async (videoId, body) => {
    const job = await originalSend(videoId, body);
    sentRevisions.push(body.base_revision);
    if (sentRevisions.length === 1) {
      const plan = await api.change(videoId, {
        base_revision: body.base_revision,
        source: 'direct',
        target: body.target,
        ops: [{ op: 'remove_scene', scene_id: view.video.scene_order[2] }],
      });
      firstResult.set(job.id, { ...job, state: 'succeeded', result: { change_id: plan.id } });
    }
    return job;
  };
  api.readJob = async (id) => firstResult.get(id) ?? originalRead(id);
  openComposer(api, <EditScreen />);
  await screen.findByRole('heading', { name: '장면 1' });
  const input = screen.getByRole('textbox', { name: '편집 요청' });
  fireEvent.change(input, { target: { value: '마지막 장면 삭제' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  await screen.findByRole('button', { name: '요청 멈추기' });
  fireEvent.change(input, { target: { value: '두 번째 요청' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  const dialog = await screen.findByRole('dialog', { name: '장면을 삭제할까요?' }, { timeout: 5000 });
  expect(sentRevisions).toEqual([view.video.revision]);
  fireEvent.click(within(dialog).getByRole('button', { name: decision }));
  await screen.findByText('바꿀 값이 없어요.', {}, { timeout: 5000 });
  expect(sentRevisions).toEqual([view.video.revision, view.video.revision + (decision === '적용' ? 1 : 0)]);
});

test('test_10a_a_stale_chat_change_is_neither_proposed_nor_reported_as_applied', async () => {
  const api = createMockEditApi(view);
  const originalSend = api.sendMessage.bind(api);
  const originalReadChange = api.readChange.bind(api);
  api.readChange = async (id) => ({ ...await originalReadChange(id), status: 'stale' });
  api.sendMessage = async (videoId, body) => {
    const job = await originalSend(videoId, body);
    const plan = await api.change(videoId, {
      base_revision: body.base_revision,
      source: 'direct',
      target: body.target,
      ops: [{ op: 'remove_scene', scene_id: view.video.scene_order[2] }],
    });
    return { ...job, state: 'succeeded', result: { change_id: plan.id } };
  };
  openComposer(api, <EditScreen />);
  await screen.findByRole('heading', { name: '장면 1' });
  const input = screen.getByRole('textbox', { name: '편집 요청' });
  fireEvent.change(input, { target: { value: '마지막 장면 삭제' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  await screen.findByText('다른 편집이 먼저 저장됐어요. 바꿀 내용을 다시 요청해 주세요.');
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.queryByText('장면을 바꿨어요.')).toBeNull();
  expect(screen.queryByText('확인할 변경이 있어요.')).toBeNull();
});

test('test_23_a_field_edit_survives_reopening', async () => {
  const api = createMockEditApi(view);
  const first = wrap(<EditScreen />, api);
  await screen.findByRole('heading', { name: '장면 1' });
  await choosePosition('왼쪽 위');
  await waitFor(() => expect(positionField().textContent).toContain('왼쪽 위'));
  first.unmount();
  cleanup();
  wrap(<EditScreen />, api);
  await screen.findByRole('heading', { name: '장면 1' });
  await waitFor(() => expect(positionField().textContent).toContain('왼쪽 위'));
});

test('test_10a_the_make_button_keeps_one_look_while_the_edit_session_loads', async () => {
  const api = createMockEditApi(view);
  const load = api.load.bind(api);
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  api.load = async (...args) => {
    await gate;
    return load(...args);
  };
  wrap(<EditNextAction />, api);

  const action = screen.getByRole('button', { name: '영상 만들기' }) as HTMLButtonElement;
  expect(action.disabled).toBe(false);
  fireEvent.click(action);
  expect(screen.queryByRole('dialog', { name: '장면 확인' })).toBeNull();

  release();
  await waitFor(() => expect(action.getAttribute('aria-busy')).toBeNull());
  expect(action.disabled).toBe(false);
  fireEvent.click(action);
  expect(await screen.findByRole('dialog', { name: '장면 확인' })).toBeTruthy();
});

test('test_10a_a_confirmed_script_opens_the_scene_check_once_the_scenes_load', async () => {
  requestSceneConfirm('v_test');
  wrap(<EditNextAction />);

  const dialog = await screen.findByRole('dialog', { name: '장면 확인' });
  fireEvent.click(within(dialog).getByRole('button', { name: '취소' }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '장면 확인' })).toBeNull());
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(screen.queryByRole('dialog', { name: '장면 확인' })).toBeNull();
});

test('test_10a_a_scene_check_asked_for_another_video_stays_closed', async () => {
  requestSceneConfirm('v_other');
  wrap(<EditNextAction />);

  await waitFor(() => expect((screen.getByRole('button', { name: '영상 만들기' }) as HTMLButtonElement).getAttribute('aria-busy')).toBeNull());
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(screen.queryByRole('dialog', { name: '장면 확인' })).toBeNull();
});

test('test_10a_stopping_the_video_says_so_in_the_conversation', async () => {
  wrap(<><EditActions /><EditChatHistory /></>);
  await startVideo();
  fireEvent.click(await screen.findByRole('button', { name: '확인 후 생성' }));
  fireEvent.click(await screen.findByRole('button', { name: /만들기 멈추기/ }, { timeout: 5000 }));

  expect(await screen.findByText('영상 만들기를 멈췄어요.')).toBeTruthy();
  expect(screen.getAllByText('영상 만들기를 멈췄어요.')).toHaveLength(1);
});
