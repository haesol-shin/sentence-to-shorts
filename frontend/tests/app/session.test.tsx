import { act, cleanup, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { shellRoutes } from '../support/api';
import { renderApp } from '../support/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
});

const PAIR_CODE = 'paircode-0123456789';

test('test_13_pair_code_becomes_a_session_and_leaves_the_address', async () => {
  const routes = shellRoutes();
  routes['POST /api/v1/session/pair'] = () => ({
    status: 200,
    body: {
      csrf_token: 'p'.repeat(40),
      profile: 'fixture',
      deployment: 'local',
      ui_language: 'en',
    },
  });

  window.location.hash = `#pair=${PAIR_CODE}`;
  const api = await renderApp(routes, { strict: true });

  expect(await screen.findByRole('heading', { name: 'What video should we make?' })).toBeTruthy();
  expect(window.location.hash).toBe('');
  expect(api.count('POST', '/api/v1/session/pair')).toBe(1);
  expect(window.localStorage.length).toBe(0);
  expect(window.sessionStorage.length).toBe(0);
});

test('test_13_a_fragment_that_is_not_a_code_is_ignored', async () => {
  window.location.hash = '#pair=short';

  const api = await renderApp();

  expect(api.count('POST', '/api/v1/session/pair')).toBe(0);
  expect(api.count('GET', '/api/v1/session/csrf')).toBe(1);
});

test('test_13_no_protected_read_runs_before_the_session_is_ready', async () => {
  const routes = shellRoutes();
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  routes['GET /api/v1/session/csrf'] = async () => {
    await gate;
    return { status: 200, body: { csrf_token: 'c'.repeat(40) } };
  };

  const api = await renderApp(routes);

  expect(api.count('GET', '/api/v1/runtime')).toBe(0);
  expect(api.count('GET', '/api/v1/catalog/format_card')).toBe(0);
  expect(api.count('GET', '/api/v1/projects')).toBe(0);
  expect(screen.queryByText('카드를 불러오지 못했어요.')).toBeNull();
  expect(screen.queryByText('최근 프로젝트를 불러오지 못했어요.')).toBeNull();

  await act(async () => {
    release();
  });

  expect(await screen.findByRole('button', { name: /딱 3가지만/ })).toBeTruthy();
  expect(api.count('GET', '/api/v1/runtime')).toBe(1);
  expect(api.count('GET', '/api/v1/catalog/format_card')).toBe(1);
  expect(api.count('GET', '/api/v1/projects')).toBe(1);
  expect(screen.queryByText('카드를 불러오지 못했어요.')).toBeNull();
  expect(screen.queryByText('최근 프로젝트를 불러오지 못했어요.')).toBeNull();
});

test('test_13_a_reload_renews_the_token_from_the_session_cookie', async () => {
  const api = await renderApp();

  expect(api.count('GET', '/api/v1/session/csrf')).toBe(1);
});

test('test_13_a_missing_session_is_told_and_the_screen_stays', async () => {
  const routes = shellRoutes();
  delete routes['GET /api/v1/session/csrf'];

  await renderApp(routes);

  expect(
    await screen.findByText('컴퓨터 화면에 보이는 연결 코드로 다시 열어 주세요.'),
  ).toBeTruthy();
  expect(screen.getByRole('heading', { name: '어떤 영상을 만들까요?' })).toBeTruthy();
});
