import { expect, test } from 'vitest';

import { prepareOf, waitingPercent } from '@/features/runtime/prepare';
import type { PrepareGroup } from '@/shared/api/client';

function group(id: PrepareGroup['id'], state: PrepareGroup['state'], done: number, total: number, extra: Partial<PrepareGroup> = {}): PrepareGroup {
  return { id, state, done, total, error_code: null, retry_at: null, ...extra };
}

test('test_21_a_korean_video_waits_only_for_the_voice_group', () => {
  const groups = [group('voice', 'ready', 100, 100), group('transcribe', 'downloading', 0, 50), group('align_en', 'queued', 0, 20)];

  expect(prepareOf(groups, 'ko')).toEqual({ state: 'ready' });
});

test('test_21_an_english_video_also_waits_for_the_english_aligner', () => {
  const groups = [group('voice', 'ready', 100, 100), group('align_en', 'downloading', 5, 20)];

  expect(prepareOf(groups, 'en')).toEqual({ state: 'waiting', percent: 87 });
});

test('test_21_the_percent_is_the_bytes_done_over_the_bytes_total_of_the_needed_groups', () => {
  const groups = [group('voice', 'downloading', 300, 1000), group('transcribe', 'downloading', 999, 1000), group('align_en', 'queued', 100, 1000)];

  expect(prepareOf(groups, 'ko')).toEqual({ state: 'waiting', percent: 30 });
  expect(prepareOf(groups, 'en')).toEqual({ state: 'waiting', percent: 20 });
});

test('test_21_the_percent_never_reads_100_before_the_groups_are_ready', () => {
  expect(prepareOf([group('voice', 'downloading', 1000, 1000)], 'ko')).toEqual({ state: 'waiting', percent: 99 });
  expect(prepareOf([group('voice', 'queued', 0, 0)], 'ko')).toEqual({ state: 'waiting', percent: 0 });
});

test('test_21_a_retrying_group_keeps_its_percent_and_names_the_next_try', () => {
  const groups = [group('voice', 'retrying', 400, 1000, { retry_at: '2026-11-21T09:00:15Z' })];

  expect(prepareOf(groups, 'ko')).toEqual({ state: 'retrying', percent: 40, retryAt: '2026-11-21T09:00:15Z' });
});

test('test_21_a_failed_group_outranks_a_retrying_or_downloading_one', () => {
  const groups = [
    group('voice', 'downloading', 10, 100),
    group('align_en', 'failed', 0, 100, { error_code: 'disk_full' }),
  ];

  expect(prepareOf(groups, 'en')).toEqual({ state: 'failed', percent: 5, errorCode: 'disk_full' });
});

test('test_21_a_missing_answer_or_unlisted_group_has_nothing_to_wait_for', () => {
  expect(prepareOf(null, 'ko')).toEqual({ state: 'ready' });
  expect(prepareOf([], 'en')).toEqual({ state: 'ready' });
});

test('test_21_only_a_downloading_or_retrying_view_has_a_button_percent', () => {
  expect(waitingPercent({ state: 'waiting', percent: 12 })).toBe(12);
  expect(waitingPercent({ state: 'retrying', percent: 12, retryAt: null })).toBe(12);
  expect(waitingPercent({ state: 'failed', percent: 12, errorCode: null })).toBeNull();
  expect(waitingPercent({ state: 'ready' })).toBeNull();
});
