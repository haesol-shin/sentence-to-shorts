import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { ExportRoute } from '@/app/routes/export';
import { TopBar } from '@/app/shell/top-bar';
import { createMockEditApi, type EditApi } from '@/features/edit/api';
import { EditProvider, useEdit } from '@/features/edit/edit-context';
import { configureExport } from '@/features/export/store';
import { refreshSession, type Language, type PrepareGroup } from '@/shared/api/client';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

import { makeView } from '../edit/fixtures';
import { stubApi as stubExportApi, unbuiltView } from '../export/fixtures';
import { stubApi } from '../support/api';

const RETRY_AT = '2026-11-21T09:00:15Z';

function group(
  id: PrepareGroup['id'],
  state: PrepareGroup['state'],
  done: number,
  extra: Partial<PrepareGroup> = {},
): PrepareGroup {
  return { id, state, done, total: 100, error_code: null, retry_at: null, ...extra };
}

let groups: PrepareGroup[];

function serve() {
  return stubApi({
    'GET /api/v1/session/csrf': () => ({ status: 200, body: { csrf_token: 'c'.repeat(40) } }),
    'GET /api/v1/runtime': () => ({ status: 200, body: { prepare: { groups } } }),
    'POST /api/v1/runtime/prepare': () => {
      groups = groups.map((item) => ({ ...item, state: item.state === 'failed' ? 'queued' : item.state }));
      return { status: 202, body: {} };
    },
  });
}

/** An edit API whose video job waits in the queue, as the server holds it for the models. */
function queuedApi(language: Language = 'ko'): EditApi {
  const view = makeView();
  view.video.settings.language = language;
  const api = createMockEditApi(view);
  const generate = api.generate.bind(api);
  const readJob = api.readJob.bind(api);
  api.generate = async (...args) => ({ ...(await generate(...args)), state: 'queued' });
  api.readJob = async (...args) => ({ ...(await readJob(...args)), state: 'queued' });
  return api;
}

/** The export step starts the job after the scenes are confirmed; this stands in for it. */
function StartVideo() {
  const edit = useEdit();
  if (!edit.confirmedForOutput || edit.video === null) return null;
  const revision = edit.video.revision;
  return (
    <button
      onClick={() => {
        edit.acknowledgeOutput();
        void edit.generateVideo(revision);
      }}
    >
      start
    </button>
  );
}

function renderEdit(api: EditApi, language: Language = 'ko') {
  return render(
    <LocaleProvider language={language} setLanguage={() => undefined}>
      <EditProvider active videoId="v_test" api={api}>
        <TopBar view="edit" videoId="v_test" onStage={() => undefined} />
        <StartVideo />
      </EditProvider>
    </LocaleProvider>,
  );
}

async function pressMake(name: string): Promise<void> {
  const action = await screen.findByRole('button', { name });
  await waitFor(() => expect((action as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(action);
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name }));
  fireEvent.click(await screen.findByRole('button', { name: 'start' }));
}

afterEach(() => {
  cleanup();
  configureExport(null);
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

test('test_21_the_edit_button_stays_pressable_while_the_voice_downloads', async () => {
  groups = [group('voice', 'downloading', 42), group('transcribe', 'queued', 0), group('align_en', 'queued', 0)];
  const api = serve();
  renderEdit(queuedApi());

  const action = await screen.findByRole('button', { name: '영상 만들기' });
  await waitFor(() => expect(api.count('GET', '/api/v1/runtime')).toBeGreaterThan(0));
  expect((action as HTMLButtonElement).disabled).toBe(false);
  expect(screen.queryByText(/준비 중/)).toBeNull();
});

test('test_21_a_pressed_edit_button_keeps_its_stop_name_and_the_percent_stands_beside_it', async () => {
  groups = [group('voice', 'downloading', 42), group('transcribe', 'queued', 0), group('align_en', 'queued', 0)];
  serve();
  renderEdit(queuedApi());

  await pressMake('영상 만들기');

  const stop = await screen.findByRole('button', { name: '만들기 멈추기' });
  expect(stop.hasAttribute('data-running')).toBe(true);
  expect(screen.getByText('준비 중 42%')).toBeTruthy();
});

test('test_21_the_edit_button_goes_back_to_stop_when_the_models_are_ready', async () => {
  groups = [group('voice', 'ready', 100), group('transcribe', 'ready', 100), group('align_en', 'ready', 100)];
  serve();
  renderEdit(queuedApi());

  await pressMake('영상 만들기');

  expect(await screen.findByRole('button', { name: /만들기 멈추기/ })).toBeTruthy();
  expect(screen.queryByText(/준비 중/)).toBeNull();
});

test('test_21_an_english_video_counts_the_english_aligner_in_the_percent', async () => {
  groups = [group('voice', 'ready', 100), group('transcribe', 'queued', 0), group('align_en', 'downloading', 50)];
  serve();
  renderEdit(queuedApi('en'), 'en');

  await pressMake('Make the video');

  expect(await screen.findByRole('button', { name: 'Stop making' })).toBeTruthy();
  expect(screen.getByText('Preparing 75%')).toBeTruthy();
});

test('test_21_a_retrying_download_stops_the_percent_and_asks_for_the_connection', async () => {
  groups = [group('voice', 'retrying', 42, { retry_at: RETRY_AT }), group('transcribe', 'queued', 0), group('align_en', 'queued', 0)];
  serve();
  renderEdit(queuedApi());

  await pressMake('영상 만들기');

  expect(await screen.findByRole('button', { name: '만들기 멈추기' })).toBeTruthy();
  expect(screen.getByText('준비 중 42%')).toBeTruthy();
  const notice = await waitFor(() => {
    const found = document.querySelector('[data-slot="prepare-notice"][data-state="retrying"]');
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  expect(notice.textContent).toContain('인터넷 연결을 확인하세요, 다시 시도하는 중');
  expect(notice.textContent).toMatch(/다음 시도 .*\d{1,2}:\d{2}:\d{2}/u);
});

test.each([
  ['download_failed', '음성 파일을 받지 못했어요'],
  ['disk_full', '디스크 공간이 모자라'],
  ['model_hash_mismatch', '받은 음성 파일이 올바르지 않아요'],
  ['download_blocked', '이 네트워크에서는 음성 파일을 받을 수 없어요'],
  ['download_too_large', '예상보다 커서 멈췄어요'],
  ['model_missing', '음성 파일을 찾을 수 없어요'],
] as const)('test_21_a_failed_download_names_%s_and_offers_a_retry', async (code, sentence) => {
  groups = [group('voice', 'failed', 0, { error_code: code }), group('transcribe', 'queued', 0), group('align_en', 'queued', 0)];
  const api = serve();
  renderEdit(queuedApi());
  await refreshSession();

  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain(sentence);
  const action = screen.getByRole('button', { name: '영상 만들기' });
  expect((action as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));

  await waitFor(() => expect(api.count('POST', '/api/v1/runtime/prepare')).toBe(1));
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
});

/** The export step on the unbuilt video, with a start that waits until `release` is called. */
function renderCheck(language: Language = 'ko') {
  configureExport(stubExportApi());
  const view = unbuiltView();
  view.video.settings.language = language;
  const api = createMockEditApi(view);
  const generate = api.generate.bind(api);
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  api.generate = async (...args) => {
    await gate;
    return generate(...args);
  };
  render(
    <LocaleProvider language={language} setLanguage={() => undefined}>
      <EditProvider active videoId="v_test" api={api}>
        <ExportRoute videoId="v_test" onStage={() => undefined} onSavePreset={() => undefined} />
      </EditProvider>
    </LocaleProvider>,
  );
  return release;
}

test('test_21_the_output_check_button_shows_the_percent_once_pressed', async () => {
  groups = [group('voice', 'downloading', 30), group('transcribe', 'queued', 0), group('align_en', 'queued', 0)];
  serve();
  const release = renderCheck();

  const make = await screen.findByRole('button', { name: '영상 만들기' });
  await waitFor(() => expect((make as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(make);

  expect(await screen.findByRole('button', { name: '준비 중 30%' })).toBeTruthy();
  release();
});

test('test_21_the_output_check_button_keeps_its_label_when_the_models_are_ready', async () => {
  groups = [group('voice', 'ready', 100), group('transcribe', 'ready', 100), group('align_en', 'ready', 100)];
  serve();
  const release = renderCheck();

  const make = await screen.findByRole('button', { name: '영상 만들기' });
  await waitFor(() => expect((make as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(make);

  await waitFor(() => expect((make as HTMLButtonElement).disabled).toBe(true));
  expect(make.textContent).toBe('영상 만들기');
  release();
});

test('test_21_the_output_check_shows_a_failed_download_with_its_retry', async () => {
  groups = [group('voice', 'failed', 0, { error_code: 'disk_full' })];
  const api = serve();
  await refreshSession();
  renderCheck();

  expect((await screen.findByText(/디스크 공간이 모자라/)).textContent).toContain('음성 준비를 멈췄어요');
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));

  await waitFor(() => expect(api.count('POST', '/api/v1/runtime/prepare')).toBe(1));
});

test('test_21_the_output_check_shows_the_retry_sentence_while_the_connection_is_down', async () => {
  groups = [group('voice', 'retrying', 42, { retry_at: RETRY_AT })];
  serve();
  renderCheck();

  const notice = await waitFor(() => {
    const found = document.querySelector('[data-slot="prepare-notice"][data-state="retrying"]');
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  expect(notice.textContent).toContain('인터넷 연결을 확인하세요, 다시 시도하는 중');
});

test('test_21_a_failed_retry_replaces_the_stop_reason_with_one_sentence_until_the_next_try', async () => {
  groups = [group('voice', 'failed', 0, { error_code: 'disk_full' })];
  let down = true;
  stubApi({
    'GET /api/v1/session/csrf': () => ({ status: 200, body: { csrf_token: 'c'.repeat(40) } }),
    'GET /api/v1/runtime': () => ({ status: 200, body: { prepare: { groups } } }),
    'POST /api/v1/runtime/prepare': () => {
      if (down) {
        return {
          status: 503,
          body: {
            type: 'https://app.invalid/problems/internal',
            title: 'internal',
            status: 503,
            detail: 'the server could not queue the preparation',
            instance: '/api/v1/runtime/prepare',
            code: 'internal',
            message_key: 'error.internal',
            retryable: true,
            errors: [],
          },
        };
      }
      groups = groups.map((item) => ({ ...item, state: 'queued' }));
      return { status: 202, body: {} };
    },
  });
  await refreshSession();
  renderCheck();
  expect((await screen.findByRole('alert')).textContent).toContain('디스크 공간이 모자라');

  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));

  await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('서버에서 문제가 생겼어요.'));
  expect(screen.getAllByRole('alert')).toHaveLength(1);
  expect((screen.getByRole('button', { name: '다시 시도' }) as HTMLButtonElement).disabled).toBe(false);

  down = false;
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
});
