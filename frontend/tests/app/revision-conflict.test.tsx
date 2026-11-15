import { cleanup, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { DRAFT_VIDEO_PATH, shellRoutes } from '../support/api';
import { COMPOSER_LABEL, FIRST_HEADING, renderApp, sendSentence } from '../support/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const conflict = {
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
};

test('test_10a_a_stale_revision_reloads_the_video_and_warns', async () => {
  const routes = shellRoutes();
  routes[`POST ${DRAFT_VIDEO_PATH}/draft`] = () => ({ status: 409, body: conflict });

  const api = await renderApp(routes);
  sendSentence('커피를 고르는 세 가지 기준');

  expect(
    await screen.findByText('다른 곳에서 먼저 바뀌었어요. 새 내용을 불러왔어요.'),
  ).toBeTruthy();
  expect(api.count('GET', DRAFT_VIDEO_PATH)).toBe(1);
  expect(screen.getByRole('heading', { name: FIRST_HEADING })).toBeTruthy();
});

test('test_10a_a_failed_send_keeps_the_typed_sentence', async () => {
  const routes = shellRoutes();
  routes[`POST ${DRAFT_VIDEO_PATH}/draft`] = () => ({ status: 409, body: conflict });

  await renderApp(routes);
  sendSentence('커피를 고르는 세 가지 기준');

  await screen.findByText('다른 곳에서 먼저 바뀌었어요. 새 내용을 불러왔어요.');
  const composer = screen.getByRole('textbox', { name: COMPOSER_LABEL });
  expect((composer as HTMLTextAreaElement).value).toBe('커피를 고르는 세 가지 기준');
});

test('test_10a_a_server_failure_says_so_and_keeps_the_first_screen', async () => {
  const routes = shellRoutes();
  routes[`POST ${DRAFT_VIDEO_PATH}/draft`] = () => ({
    status: 500,
    body: { ...conflict, status: 500, code: 'internal', message_key: 'error.internal' },
  });

  await renderApp(routes);
  sendSentence('커피를 고르는 세 가지 기준');

  expect(await screen.findByText('서버에서 문제가 생겼어요.')).toBeTruthy();
  expect(screen.getByRole('heading', { name: FIRST_HEADING })).toBeTruthy();
});
