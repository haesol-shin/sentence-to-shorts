import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import {
  DRAFT_JOB_PATH,
  DRAFT_VIDEO_PATH,
  shellRoutes,
  stubApi,
} from '../support/api';
import { renderApp, sendSentence } from '../support/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('test_10a_first_screen_lists_three_cards_and_recent_projects', async () => {
  await renderApp();

  expect(await screen.findByRole('button', { name: /딱 3가지만/ })).toBeTruthy();
  expect(screen.getByRole('button', { name: /○○로 치면/ })).toBeTruthy();
  expect(screen.getByRole('button', { name: /만약 ~라면/ })).toBeTruthy();
  expect(screen.getByText('커피 시리즈')).toBeTruthy();
});

test('test_10a_picking_a_card_marks_the_composer', async () => {
  await renderApp();

  fireEvent.click(await screen.findByRole('button', { name: /만약 ~라면/ }));
  expect(screen.getByText('카드: 만약 ~라면?')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: '고른 카드 지우기' }));
  await waitFor(() => expect(screen.queryByText('카드: 만약 ~라면?')).toBeNull());
});

test('test_10a_a_picked_card_travels_with_the_sentence', async () => {
  const api = await renderApp();

  fireEvent.click(await screen.findByRole('button', { name: /딱 3가지만/ }));
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  const draft = api.calls.find((call) => call.path === `${DRAFT_VIDEO_PATH}/draft`);
  expect(draft?.body).toMatchObject({ card_id: 'just_three' });
});

test('test_10a_sentence_send_starts_a_draft_job', async () => {
  const api = await renderApp();

  sendSentence('커피를 고르는 세 가지 기준');

  expect(await screen.findByRole('heading', { name: '컨셉' })).toBeTruthy();
  expect(await screen.findByText('차례를 기다리는 중이에요.')).toBeTruthy();
  expect(api.count('GET', DRAFT_JOB_PATH)).toBeGreaterThan(0);

  const draft = api.calls.find((call) => call.path === `${DRAFT_VIDEO_PATH}/draft`);
  expect(draft?.body).toEqual({
    base_revision: 1,
    message: '커피를 고르는 세 가지 기준',
    card_id: null,
  });
  expect(draft?.headers['x-csrf-token']).toBe('c'.repeat(40));

  const keys = api.calls
    .filter((call) => call.method === 'POST')
    .map((call) => call.headers['idempotency-key']);
  expect(keys).toHaveLength(3);
  expect(keys.every((key) => /^[A-Za-z0-9_-]{8,64}$/u.test(key ?? ''))).toBe(true);
  expect(new Set(keys).size).toBe(3);
});

test('test_16_language_switch_turns_the_screen_english', async () => {
  await renderApp();

  fireEvent.click(screen.getByRole('button', { name: 'English' }));

  expect(await screen.findByRole('heading', { name: 'What video should we make?' })).toBeTruthy();
  expect(document.documentElement.lang).toBe('en');
});

test('test_10a_recent_projects_failure_does_not_claim_an_empty_list', async () => {
  const routes = shellRoutes();
  delete routes['GET /api/v1/projects'];
  stubApi(routes);

  await renderApp(routes);

  expect(await screen.findByText('최근 프로젝트를 불러오지 못했어요.')).toBeTruthy();
  expect(screen.queryByText('아직 만든 영상이 없어요.')).toBeNull();
});
