import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { usePrepare } from '@/features/runtime/use-prepare';
import { refreshSession, type Language, type PrepareGroup } from '@/shared/api/client';

import { stubApi, type ApiStub } from '../support/api';

function group(id: PrepareGroup['id'], state: PrepareGroup['state'], done: number): PrepareGroup {
  return { id, state, done, total: 100, error_code: null, retry_at: null };
}

function Probe({ language }: { language: Language | null }) {
  const { view, retry } = usePrepare(language);
  return (
    <button onClick={retry}>
      {view.state}
    </button>
  );
}

let groups: PrepareGroup[];
let api: ApiStub;

function serve(): ApiStub {
  return stubApi({
    'GET /api/v1/session/csrf': () => ({ status: 200, body: { csrf_token: 'c'.repeat(40) } }),
    'GET /api/v1/runtime': () => ({ status: 200, body: { prepare: { groups } } }),
    'POST /api/v1/runtime/prepare': () => {
      groups = groups.map((item) => (item.state === 'failed' ? { ...item, state: 'queued' } : item));
      return { status: 202, body: {} };
    },
  });
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function setHidden(hidden: boolean): void {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: hidden ? 'hidden' : 'visible' });
  document.dispatchEvent(new Event('visibilitychange'));
}

beforeEach(() => {
  vi.useFakeTimers();
  groups = [group('voice', 'downloading', 10), group('transcribe', 'queued', 0), group('align_en', 'queued', 0)];
  api = serve();
});

afterEach(() => {
  cleanup();
  setHidden(false);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test('test_21_the_runtime_is_read_every_second_while_a_needed_group_is_not_ready', async () => {
  render(<Probe language="ko" />);
  await advance(0);
  expect(api.count('GET', '/api/v1/runtime')).toBe(1);
  expect(screen.getByRole('button').textContent).toBe('waiting');

  await advance(3000);
  expect(api.count('GET', '/api/v1/runtime')).toBe(4);
});

test('test_21_a_hidden_tab_reads_every_five_seconds', async () => {
  setHidden(true);
  render(<Probe language="ko" />);
  await advance(0);
  expect(api.count('GET', '/api/v1/runtime')).toBe(1);

  await advance(4999);
  expect(api.count('GET', '/api/v1/runtime')).toBe(1);
  await advance(1);
  expect(api.count('GET', '/api/v1/runtime')).toBe(2);
  await advance(10_000);
  expect(api.count('GET', '/api/v1/runtime')).toBe(4);
});

test('test_21_the_reading_stops_once_every_needed_group_is_ready', async () => {
  render(<Probe language="ko" />);
  await advance(0);
  groups = groups.map((item) => (item.id === 'voice' ? { ...item, state: 'ready', done: 100 } : item));
  await advance(1000);
  expect(screen.getByRole('button').textContent).toBe('ready');
  const reads = api.count('GET', '/api/v1/runtime');

  await advance(10_000);
  expect(api.count('GET', '/api/v1/runtime')).toBe(reads);
});

test('test_21_a_ready_install_is_read_once', async () => {
  groups = groups.map((item) => ({ ...item, state: 'ready', done: 100 }));
  render(<Probe language="en" />);
  await advance(10_000);

  expect(api.count('GET', '/api/v1/runtime')).toBe(1);
  expect(screen.getByRole('button').textContent).toBe('ready');
});

test('test_21_a_group_the_video_does_not_need_does_not_keep_the_reading_going', async () => {
  groups = [group('voice', 'ready', 100), group('transcribe', 'downloading', 5), group('align_en', 'queued', 0)];
  render(<Probe language="ko" />);
  await advance(10_000);

  expect(api.count('GET', '/api/v1/runtime')).toBe(1);
});

test('test_21_nothing_is_read_until_the_video_language_is_known', async () => {
  render(<Probe language={null} />);
  await advance(10_000);

  expect(api.count('GET', '/api/v1/runtime')).toBe(0);
  expect(screen.getByRole('button').textContent).toBe('ready');
});

test('test_21_a_read_that_never_answered_counts_as_ready_and_is_not_repeated', async () => {
  stubApi({});
  render(<Probe language="ko" />);
  await advance(10_000);

  expect(screen.getByRole('button').textContent).toBe('ready');
});

test('test_21_a_failed_read_keeps_the_last_state_and_keeps_reading', async () => {
  let down = false;
  api = stubApi({
    'GET /api/v1/runtime': () => (down ? { status: 500 } : { status: 200, body: { prepare: { groups } } }),
  });
  render(<Probe language="ko" />);
  await advance(0);
  down = true;
  await advance(3000);

  expect(screen.getByRole('button').textContent).toBe('waiting');
  expect(api.count('GET', '/api/v1/runtime')).toBe(4);
});

test('test_21_leaving_the_screen_stops_the_reading', async () => {
  const view = render(<Probe language="ko" />);
  await advance(0);
  view.unmount();
  const reads = api.count('GET', '/api/v1/runtime');

  await advance(10_000);
  expect(api.count('GET', '/api/v1/runtime')).toBe(reads);
});

test('test_21_retry_queues_the_failed_groups_again_and_reads_at_once', async () => {
  groups = [{ ...group('voice', 'failed', 0), error_code: 'disk_full' }];
  render(<Probe language="ko" />);
  await advance(0);
  await act(async () => {
    await refreshSession();
  });
  expect(screen.getByRole('button').textContent).toBe('failed');

  fireEvent.click(screen.getByRole('button'));
  await advance(0);

  expect(api.count('POST', '/api/v1/runtime/prepare')).toBe(1);
  expect(screen.getByRole('button').textContent).toBe('waiting');
});
