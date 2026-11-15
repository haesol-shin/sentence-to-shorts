import { afterEach, expect, test, vi } from 'vitest';

import {
  createProject,
  messageKeyOf,
  newIdempotencyKey,
  OfflineError,
  readJob,
  refreshSession,
  SessionMissingError,
  submitDraft,
  ApiProblemError,
  RevisionConflictError,
} from '@/shared/api/client';

import {
  DRAFT_JOB,
  DRAFT_VIDEO,
  DRAFT_VIDEO_PATH,
  draftJob,
  draftVideo,
  shellRoutes,
  stubApi,
} from '../support/api';

afterEach(() => {
  vi.unstubAllGlobals();
});

test('test_10a_each_action_gets_a_fresh_key', async () => {
  const api = stubApi(shellRoutes());
  await refreshSession();

  await createProject({ language: 'ko' });
  await createProject({ language: 'ko' });

  const keys = api.calls
    .filter((call) => call.method === 'POST')
    .map((call) => call.headers['idempotency-key']);
  expect(keys).toHaveLength(2);
  expect(keys[0]).not.toBe(keys[1]);
  for (const key of keys) {
    expect(key).toMatch(/^[A-Za-z0-9_-]{8,64}$/u);
  }
});

test('test_10a_a_change_carries_the_base_revision_and_the_session_token', async () => {
  const api = stubApi(shellRoutes());
  await refreshSession();

  await submitDraft(DRAFT_VIDEO, { base_revision: 7, message: '더 짧게', card_id: null });

  const call = api.calls.at(-1);
  expect(call?.body).toEqual({ base_revision: 7, message: '더 짧게', card_id: null });
  expect(call?.headers['x-csrf-token']).toBe('c'.repeat(40));
});

test('test_13_a_change_without_a_session_never_leaves_the_tab', async () => {
  const api = stubApi(shellRoutes());

  await expect(
    submitDraft(DRAFT_VIDEO, { base_revision: 1, message: '한 문장', card_id: null }),
  ).rejects.toBeInstanceOf(SessionMissingError);
  expect(api.calls).toHaveLength(0);
});

test('test_3_a_problem_body_keeps_its_message_key', async () => {
  const routes = shellRoutes();
  routes[`POST ${DRAFT_VIDEO_PATH}/draft`] = () => ({
    status: 409,
    body: {
      type: 'https://app.invalid/problems/concept_locked',
      title: 'concept_locked',
      status: 409,
      detail: 'the concept is confirmed',
      instance: `${DRAFT_VIDEO_PATH}/draft`,
      code: 'concept_locked',
      message_key: 'error.concept_locked',
      retryable: false,
      errors: [],
    },
  });
  stubApi(routes);
  await refreshSession();

  const error = await submitDraft(DRAFT_VIDEO, {
    base_revision: 1,
    message: '한 문장',
    card_id: null,
  }).catch((thrown: unknown) => thrown);

  expect(error).toBeInstanceOf(ApiProblemError);
  expect(messageKeyOf(error)).toBe('error.concept_locked');
});

test('test_10a_a_stale_revision_comes_back_with_the_newest_video', async () => {
  const routes = shellRoutes();
  routes[`POST ${DRAFT_VIDEO_PATH}/draft`] = () => ({
    status: 409,
    body: {
      type: 'https://app.invalid/problems/revision_conflict',
      title: 'revision_conflict',
      status: 409,
      detail: 'the base revision is not the head',
      instance: `${DRAFT_VIDEO_PATH}/draft`,
      code: 'revision_conflict',
      message_key: 'error.revision_conflict',
      retryable: true,
      errors: [],
      current_revision: 4,
    },
  });
  stubApi(routes);
  await refreshSession();

  const error = await submitDraft(DRAFT_VIDEO, {
    base_revision: 1,
    message: '한 문장',
    card_id: null,
  }).catch((thrown: unknown) => thrown);

  expect(error).toBeInstanceOf(RevisionConflictError);
  expect((error as RevisionConflictError).currentRevision).toBe(4);
});

test('test_3_a_request_that_never_arrives_is_a_network_failure', async () => {
  stubApi(shellRoutes());
  vi.stubGlobal('fetch', () => Promise.reject(new TypeError('connect ECONNREFUSED')));

  const error = await refreshSession().catch((thrown: unknown) => thrown);

  expect(error).toBeInstanceOf(OfflineError);
  expect(messageKeyOf(error)).toBe('error.network');
});

test('test_3_a_job_read_passes_the_etag_and_accepts_a_304', async () => {
  const routes = shellRoutes();
  let reads = 0;
  routes[`GET /api/v1/jobs/${DRAFT_JOB}`] = () => {
    reads += 1;
    return reads === 1 ? { status: 200, body: draftJob, headers: { etag: 'W/"3"' } } : { status: 304 };
  };
  const api = stubApi(routes);

  const first = await readJob(DRAFT_JOB, null);
  const second = await readJob(DRAFT_JOB, first.etag);

  expect(first.job?.id).toBe(DRAFT_JOB);
  expect(second.notModified).toBe(true);
  expect(second.job).toBeNull();
  expect(api.calls[1]?.headers['if-none-match']).toBe('W/"3"');
});

test('test_10a_the_key_shape_fits_the_contract', () => {
  expect(newIdempotencyKey()).toMatch(/^[A-Za-z0-9_-]{8,64}$/u);
  expect(draftVideo.revision).toBe(1);
});
