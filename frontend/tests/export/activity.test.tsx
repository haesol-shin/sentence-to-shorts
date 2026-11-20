import { act, cleanup, render, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { flushActivity, useActivityReporting, useActivityUnsent } from '@/features/export/activity';
import { MAX_ACTIVITY_SPANS } from '@/features/export/api';
import { ActivityTracker, jobUsageMetrics, spanMs } from '@/features/export/model';
import { configureExport } from '@/features/export/store';

import { job, stubApi } from './fixtures';

let visibility: DocumentVisibilityState = 'visible';

function setVisibility(next: DocumentVisibilityState): void {
  visibility = next;
  document.dispatchEvent(new Event('visibilitychange'));
}

function Probe({ videoId, waiting = false, enabled = true }: { videoId: string; waiting?: boolean; enabled?: boolean }) {
  useActivityReporting(videoId, waiting, enabled);
  return null;
}

beforeEach(() => {
  visibility = 'visible';
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
  vi.useFakeTimers();
  vi.setSystemTime(1_000_000);
});

afterEach(() => {
  cleanup();
  configureExport(null);
  window.sessionStorage.clear();
  vi.useRealTimers();
});

test('hidden time is not recorded, even if waiting changes while hidden', async () => {
  const videoId = 'v_test_activity_visibility';
  const api = stubApi();
  configureExport(api);
  const view = render(<Probe videoId={videoId} />);

  vi.advanceTimersByTime(10_000);
  await act(async () => setVisibility('hidden'));
  vi.advanceTimersByTime(25_000);
  view.rerender(<Probe videoId={videoId} waiting />);
  setVisibility('visible');
  vi.advanceTimersByTime(5_000);
  view.unmount();

  const sent = api.recordActivity.mock.calls.flatMap(([, spans]) => [...spans]);
  expect(spanMs(sent, 'active')).toBe(10_000);
  expect(spanMs(sent, 'waiting')).toBe(5_000);
  expect(sent).toEqual([
    { kind: 'active', start_ms: 1_000_000, end_ms: 1_010_000 },
    { kind: 'waiting', start_ms: 1_035_000, end_ms: 1_040_000 },
  ]);
});

test('a real waiting transition splits time, while unchanged props and disabled time do not', () => {
  const videoId = 'v_test_activity_waiting';
  const api = stubApi();
  configureExport(api);
  const view = render(<Probe videoId={videoId} />);

  vi.advanceTimersByTime(3_000);
  view.rerender(<Probe videoId={videoId} />);
  vi.advanceTimersByTime(2_000);
  view.rerender(<Probe videoId={videoId} waiting />);
  vi.advanceTimersByTime(4_000);
  view.rerender(<Probe videoId={videoId} waiting enabled={false} />);
  vi.advanceTimersByTime(5_000);
  view.unmount();

  const sent = api.recordActivity.mock.calls.flatMap(([, spans]) => [...spans]);
  expect(sent).toEqual([
    { kind: 'active', start_ms: 1_000_000, end_ms: 1_005_000 },
    { kind: 'waiting', start_ms: 1_005_000, end_ms: 1_009_000 },
  ]);
});

test('each span is closed once without overlapping its successor', () => {
  const tracker = new ActivityTracker();
  tracker.update('active', 0);
  const first = tracker.take(10_000);
  const second = tracker.take(25_000);
  tracker.update(null, 30_000);
  const third = tracker.take(40_000);

  expect([...first, ...second, ...third].map((span) => [span.start_ms, span.end_ms])).toEqual([
    [0, 10_000],
    [10_000, 25_000],
    [25_000, 30_000],
  ]);
});

test('an ambiguous batch is never replayed, even after unmount and reload', async () => {
  const videoId = 'v_test_activity_ambiguous';
  const api = stubApi();
  api.recordActivity.mockRejectedValueOnce(new Error('response lost'));
  configureExport(api);

  const view = render(<Probe videoId={videoId} />);
  const unsent = renderHook(() => useActivityUnsent(videoId));
  expect(unsent.result.current).toBe(false);
  vi.advanceTimersByTime(4_000);
  act(() => flushActivity(videoId));
  expect(unsent.result.current).toBe(true);
  vi.advanceTimersByTime(6_000);
  await act(async () => view.unmount());
  expect(api.recordActivity).toHaveBeenCalledTimes(1);

  expect(unsent.result.current).toBe(true);
  unsent.unmount();

  // Re-import after clearing module state so only the browser journal survives.
  vi.resetModules();
  const reloadedActivity = await import('@/features/export/activity');
  const reloadedStore = await import('@/features/export/store');
  reloadedStore.configureExport(api);
  const afterReload = renderHook(() => reloadedActivity.useActivityUnsent(videoId));
  const otherVideo = renderHook(() => reloadedActivity.useActivityUnsent('v_test_activity_other'));
  expect(afterReload.result.current).toBe(true);
  expect(otherVideo.result.current).toBe(false);
  await act(async () => reloadedActivity.flushActivity(videoId));
  expect(api.recordActivity.mock.calls).toEqual([
    [videoId, [{ kind: 'active', start_ms: 1_000_000, end_ms: 1_004_000 }]],
    [videoId, [{ kind: 'active', start_ms: 1_004_000, end_ms: 1_010_000 }]],
  ]);
  expect(afterReload.result.current).toBe(true);
  reloadedStore.configureExport(null);
});

test('a flush sends one bounded batch, then the next flush sends only the remainder', async () => {
  const videoId = 'v_test_activity_batch';
  const api = stubApi();
  configureExport(api);
  const view = render(<Probe videoId={videoId} />);
  const unsent = renderHook(() => useActivityUnsent(videoId));
  for (let i = 1; i <= MAX_ACTIVITY_SPANS + 1; i += 1) {
    vi.advanceTimersByTime(1);
    view.rerender(<Probe videoId={videoId} waiting={i % 2 === 1} />);
  }

  await act(async () => flushActivity(videoId));
  expect(api.recordActivity).toHaveBeenCalledTimes(1);
  expect(api.recordActivity.mock.calls[0]?.[1]).toHaveLength(MAX_ACTIVITY_SPANS);
  expect(unsent.result.current).toBe(true);
  await act(async () => flushActivity(videoId));
  expect(api.recordActivity).toHaveBeenCalledTimes(2);
  expect(api.recordActivity.mock.calls[1]?.[1]).toEqual([
    { kind: 'active', start_ms: 1_000_000 + MAX_ACTIVITY_SPANS, end_ms: 1_000_001 + MAX_ACTIVITY_SPANS },
  ]);
  expect(unsent.result.current).toBe(false);
  view.unmount();
});

test('generation time and distinct rebuilt scenes use job evidence, not unrelated jobs', () => {
  const videoId = 'v_test_job_metrics';
  const first = {
    ...job('generate', 'succeeded', { rebuilt_scene_ids: ['scene-one', 'scene-one'] }),
    video_id: videoId,
    started_at: '2026-11-20T00:00:01Z',
    ended_at: '2026-11-20T00:00:08Z',
  };
  const second = {
    ...job('generate', 'succeeded', { stages: [{ rebuilt_scene_ids: ['scene-one', 'scene-two'] }] }),
    id: 'j_test_second_generate',
    video_id: videoId,
    started_at: '2026-11-20T00:00:10Z',
    ended_at: '2026-11-20T00:00:15Z',
  };
  const preview = { ...first, kind: 'preview' as const, result: { rebuilt_scene_ids: ['scene-three'] } };
  const anotherVideo = { ...first, video_id: 'v_test_other_video', result: { rebuilt_scene_ids: ['scene-four'] } };

  expect(jobUsageMetrics(videoId, [first, second, preview, anotherVideo]))
    .toEqual({ durationMs: 12_000, rebuiltCount: 2, tokens: null });
});

test('checkpoints do not prove regeneration, but an explicitly empty result proves zero', () => {
  const videoId = 'v_test_unknown_metrics';
  const cached = { ...job('generate', 'succeeded'), video_id: videoId };
  cached.checkpoints = [{ stage: 'clip', scene_id: 'scene-one', line_id: null, artifact_id: 'artifact', digest: '0'.repeat(64) }];
  expect(jobUsageMetrics(videoId, [cached])).toEqual({ durationMs: null, rebuiltCount: null, tokens: null });
  expect(jobUsageMetrics(videoId, [{ ...cached, result: { rebuilt_scene_ids: [] } }]).rebuiltCount).toBe(0);
});

test('recorded token zero is a measurement, and missing token counts are unknown', () => {
  const videoId = 'v_test_token_metrics';
  const usage = {
    stage: 'llm_precheck' as const,
    provider: 'synthetic',
    model: 'synthetic',
    effort: null,
    input_tokens: 0,
    output_tokens: 14,
    cache_read_tokens: null,
    retries: 0,
    wall_ms: 10,
  };
  const precheck = { ...job('precheck', 'succeeded'), video_id: videoId, usage: [usage] };
  expect(jobUsageMetrics(videoId, [precheck]).tokens).toEqual({ input: 0, output: 14 });
  expect(jobUsageMetrics(videoId, [{
    ...precheck,
    usage: [usage, { ...usage, input_tokens: null }],
  }]).tokens).toBeNull();
});
