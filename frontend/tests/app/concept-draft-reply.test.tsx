import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { ConceptApiError, createMockConceptApi, type MockConceptApi } from '@/features/concept/api';
import { configureConceptApi, resetConceptSessions } from '@/features/concept/store';

import { DRAFT_JOB_PATH, DRAFT_VIDEO, draftAnswer, shellRoutes } from '../support/api';
import { renderApp, sendSentence } from '../support/render';

let api: MockConceptApi;

function conversation(): HTMLElement {
  const node = document.querySelector<HTMLElement>('[data-slot="conversation"]');
  if (node === null) throw new Error('The conversation is missing');
  return node;
}

beforeEach(() => {
  api = createMockConceptApi();
  configureConceptApi(api);
});

afterEach(() => {
  resetConceptSessions();
  cleanup();
  vi.unstubAllGlobals();
});

test('test_10a_the_first_concept_reply_waits_for_the_post_draft_read', async () => {
  let release: (() => void) | null = null;
  let readStarted = false;
  const load = api.load.bind(api);
  api.load = (videoId) => {
    readStarted = true;
    return new Promise((resolve) => {
      release = () => resolve(load(videoId));
    });
  };
  const routes = shellRoutes();
  let state = 'queued';
  routes[`GET ${DRAFT_JOB_PATH}`] = () => ({ status: 200, body: draftAnswer(state) });

  await renderApp(routes);
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });
  expect(conversation().textContent).toContain('문장으로 컨셉 초안을 쓰고 있어요.');

  state = 'succeeded';
  await waitFor(() => expect(readStarted).toBe(true), { timeout: 10000 });
  // The draft is done, but the values it wrote are not in the screen yet.
  expect(conversation().textContent).toContain('문장으로 컨셉 초안을 쓰고 있어요.');
  expect(conversation().textContent).not.toContain('이야기 방식은');

  await act(async () => {
    release?.();
  });
  await waitFor(() => expect(conversation().textContent).toContain('이야기 방식은'));
  expect(conversation().textContent).not.toContain('문장으로 컨셉 초안을 쓰고 있어요.');
}, 20000);

test('test_10a_a_failed_post_draft_read_keeps_its_error_until_a_successful_read', async () => {
  let reads = 0;
  api.load = () => {
    reads += 1;
    return Promise.reject(new ConceptApiError('internal', 500, 'Read failed'));
  };
  const routes = shellRoutes();
  let state = 'queued';
  routes[`GET ${DRAFT_JOB_PATH}`] = () => ({ status: 200, body: draftAnswer(state) });

  await renderApp(routes);
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  state = 'succeeded';
  await waitFor(
    () => expect(reads).toBeGreaterThanOrEqual(1),
    { timeout: 15000 },
  );
  // A failed read leaves the screen error, never a success reply from defaults.
  expect(conversation().textContent).not.toContain('이야기 방식은');
  expect(document.querySelector('.concept-review[role="alert"]')?.textContent)
    .toContain('작업을 마치지 못했어요.');

  // Another read attempt is allowed, but only success may take the error away.
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  await waitFor(() => expect(reads).toBeGreaterThanOrEqual(2), { timeout: 15000 });
  expect(conversation().textContent).not.toContain('이야기 방식은');
  expect(document.querySelector('.concept-review[role="alert"]')?.textContent)
    .toContain('작업을 마치지 못했어요.');
}, 30000);

test('test_10a_an_attachment_success_does_not_clear_the_read_error', async () => {
  let releaseMessage: (() => void) | null = null;
  let messageStarted = false;
  const message = api.message.bind(api);
  api.message = (videoId, text, attachments) => {
    messageStarted = true;
    return new Promise((resolve) => {
      releaseMessage = () => resolve(message(videoId, text, attachments));
    });
  };
  api.load = () => Promise.reject(new ConceptApiError('internal', 500, 'Read failed'));
  const routes = shellRoutes();
  let state = 'queued';
  routes[`GET ${DRAFT_JOB_PATH}`] = () => ({ status: 200, body: draftAnswer(state) });

  await renderApp(routes);
  const input = document.querySelector<HTMLInputElement>('input[type="file"][data-kind="reference"]');
  if (input === null) throw new Error('The reference input is missing');
  fireEvent.change(input, {
    target: { files: [new File(['video'], 'clip.mp4', { type: 'video/mp4' })] },
  });
  await waitFor(() =>
    expect(document.querySelectorAll('[data-slot="composer-attachment"]')).toHaveLength(1));

  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });
  state = 'succeeded';
  await waitFor(() => expect(messageStarted).toBe(true), { timeout: 15000 });
  const alert = () => document.querySelector('.concept-review[role="alert"]')?.textContent ?? '';
  await waitFor(() => expect(alert()).toContain('작업을 마치지 못했어요.'));

  await act(async () => {
    releaseMessage?.();
    await Promise.resolve();
  });
  await waitFor(() => expect(alert()).toContain('작업을 마치지 못했어요.'));
  expect(conversation().textContent).not.toContain('이야기 방식은');
}, 30000);

test('test_10a_an_unapplied_draft_never_writes_the_first_reply', async () => {
  const routes = shellRoutes();
  let state = 'queued';
  routes[`GET ${DRAFT_JOB_PATH}`] = () => ({
    status: 200,
    body: draftAnswer(state, 'proposed'),
  });

  await renderApp(routes);
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  state = 'succeeded';
  await waitFor(
    () => expect(conversation().textContent).not.toContain('문장으로 컨셉 초안을 쓰고 있어요.'),
    { timeout: 15000 },
  );
  // The draft proposed rather than wrote values, so the defaults are not a reply.
  expect(conversation().textContent).not.toContain('이야기 방식은');
}, 25000);

test('test_10a_a_direct_pick_during_the_draft_keeps_the_new_reply', async () => {
  const routes = shellRoutes();
  let state = 'queued';
  routes[`GET ${DRAFT_JOB_PATH}`] = () => ({ status: 200, body: draftAnswer(state) });

  await renderApp(routes);
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });
  const card = screen.getByRole<HTMLButtonElement>('button', { name: '만약 ~라면?' });
  await waitFor(() => expect(card.disabled).toBe(false));
  fireEvent.click(card);
  expect(card.getAttribute('aria-pressed')).toBe('true');

  const stored = api.sessions.get(DRAFT_VIDEO);
  if (stored === undefined) throw new Error('The concept session is missing');
  stored.settings.target_duration_s = 120;
  stored.settings.origins['/target_duration_s'] = 'llm';

  state = 'succeeded';
  await waitFor(
    () => expect(conversation().textContent).toContain('길이는 2분'),
    { timeout: 15000 },
  );
  expect(conversation().textContent).not.toContain('길이는 1분');
  expect(card.getAttribute('aria-pressed')).toBe('true');
}, 25000);

test('test_10a_a_held_attachment_neither_keeps_nor_removes_the_first_reply', async () => {
  let rejectMessage: ((error: unknown) => void) | null = null;
  let messageStarted = false;
  api.message = () => {
    messageStarted = true;
    return new Promise((_resolve, reject) => {
      rejectMessage = reject;
    });
  };
  const routes = shellRoutes();
  let state = 'queued';
  routes[`GET ${DRAFT_JOB_PATH}`] = () => ({ status: 200, body: draftAnswer(state) });

  await renderApp(routes);
  const input = document.querySelector<HTMLInputElement>('input[type="file"][data-kind="reference"]');
  if (input === null) throw new Error('The reference input is missing');
  fireEvent.change(input, {
    target: { files: [new File(['video'], 'clip.mp4', { type: 'video/mp4' })] },
  });
  await waitFor(() =>
    expect(document.querySelectorAll('[data-slot="composer-attachment"]')).toHaveLength(1));

  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  state = 'succeeded';
  await waitFor(() => expect(messageStarted).toBe(true), { timeout: 15000 });
  // The concept values are here; the held upload must not hold the reply.
  await waitFor(
    () => expect(conversation().textContent).toContain('이야기 방식은'),
    { timeout: 15000 },
  );
  expect(conversation().textContent).not.toContain('문장으로 컨셉 초안을 쓰고 있어요.');

  // A later attachment failure is its own notice and leaves the read reply.
  await act(async () => {
    rejectMessage?.(new ConceptApiError('internal', 500, 'Upload failed'));
  });
  await waitFor(() =>
    expect(document.querySelector('.concept-review[role="alert"]')?.textContent)
      .toContain('작업을 마치지 못했어요.'));
  expect(conversation().textContent).toContain('이야기 방식은');
}, 30000);
