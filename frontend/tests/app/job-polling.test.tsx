import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { useJob } from '@/shared/lib/use-job';

import { DRAFT_JOB, DRAFT_JOB_PATH, draftJob, shellRoutes, stubApi } from '../support/api';

function setVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: state });
  document.dispatchEvent(new Event('visibilitychange'));
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
});

test('test_3_job_lookup_reads_once_before_the_first_wait', async () => {
  const api = stubApi(shellRoutes());
  const { result } = renderHook(() => useJob(DRAFT_JOB));

  await act(async () => undefined);

  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(1);
  expect(result.current.job?.state).toBe('queued');
});

test('test_3_job_lookup_repeats_every_second_in_a_visible_tab', async () => {
  const api = stubApi(shellRoutes());
  renderHook(() => useJob(DRAFT_JOB));

  await act(async () => undefined);
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(1);

  await act(async () => {
    vi.advanceTimersByTime(1000);
  });
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(2);

  await act(async () => {
    vi.advanceTimersByTime(1000);
  });
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(3);
});

test('test_3_job_lookup_waits_five_seconds_in_a_hidden_tab', async () => {
  const api = stubApi(shellRoutes());
  renderHook(() => useJob(DRAFT_JOB));

  await act(async () => undefined);
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(1);

  act(() => setVisibility('hidden'));
  await act(async () => {
    vi.advanceTimersByTime(1000);
  });
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(1);

  await act(async () => {
    vi.advanceTimersByTime(4000);
  });
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(2);
});

test('test_3_job_lookup_sends_the_etag_and_keeps_the_job_on_304', async () => {
  const routes = shellRoutes();
  let reads = 0;
  routes[`GET ${DRAFT_JOB_PATH}`] = () => {
    reads += 1;
    return reads === 1
      ? { status: 200, body: draftJob, headers: { etag: 'W/"7"' } }
      : { status: 304 };
  };
  const api = stubApi(routes);

  const { result } = renderHook(() => useJob(DRAFT_JOB));
  await act(async () => undefined);
  await act(async () => {
    vi.advanceTimersByTime(1000);
  });

  expect(api.calls[0]?.headers['if-none-match']).toBeUndefined();
  expect(api.calls[1]?.headers['if-none-match']).toBe('W/"7"');
  expect(result.current.job?.state).toBe('queued');
});

test('test_3_job_lookup_stops_when_the_job_ends', async () => {
  const routes = shellRoutes();
  routes[`GET ${DRAFT_JOB_PATH}`] = () => ({
    status: 200,
    body: { ...draftJob, state: 'succeeded' },
  });
  const api = stubApi(routes);

  renderHook(() => useJob(DRAFT_JOB));
  await act(async () => undefined);
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });

  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(1);
});

test('test_3_job_lookup_keeps_one_read_and_one_timer', async () => {
  const routes = shellRoutes();
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let reads = 0;
  routes[`GET ${DRAFT_JOB_PATH}`] = async () => {
    reads += 1;
    if (reads === 1) {
      await gate;
    }
    return { status: 200, body: draftJob };
  };
  const api = stubApi(routes);

  renderHook(() => useJob(DRAFT_JOB));
  await act(async () => undefined);
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(1);

  // A tab switch while the read is out must not start a second one.
  act(() => setVisibility('hidden'));
  await act(async () => {
    vi.advanceTimersByTime(200);
  });
  act(() => setVisibility('visible'));
  await act(async () => {
    vi.advanceTimersByTime(900);
  });
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(1);

  await act(async () => {
    release();
  });
  await act(async () => {
    vi.advanceTimersByTime(999);
  });
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(1);

  await act(async () => {
    vi.advanceTimersByTime(1);
  });
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(2);
});

test('test_3_job_lookup_never_walks_back_from_a_finished_job', async () => {
  const routes = shellRoutes();
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  routes[`GET ${DRAFT_JOB_PATH}`] = async () => {
    await gate;
    return { status: 200, body: { ...draftJob, state: 'succeeded' } };
  };
  const api = stubApi(routes);

  const { result } = renderHook(() => useJob(DRAFT_JOB));
  await act(async () => undefined);

  act(() => setVisibility('hidden'));
  await act(async () => {
    vi.advanceTimersByTime(50);
  });
  act(() => setVisibility('visible'));
  await act(async () => {
    release();
  });

  expect(result.current.job?.state).toBe('succeeded');

  await act(async () => {
    vi.advanceTimersByTime(10000);
  });
  expect(api.count('GET', DRAFT_JOB_PATH)).toBe(1);
  expect(result.current.job?.state).toBe('succeeded');
});
