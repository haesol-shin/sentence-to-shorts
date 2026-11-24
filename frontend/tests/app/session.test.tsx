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

function problem(code: string, messageKey: string, status: number): Record<string, unknown> {
  return {
    type: `https://app.invalid/problems/${code}`,
    title: code,
    status,
    detail: code,
    instance: '/api/v1/session',
    code,
    message_key: messageKey,
    retryable: status === 429,
  };
}

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

  expect(await screen.findByRole('heading', { name: 'Make a video from one sentence' })).toBeTruthy();
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

  await act(async () => {
    release();
  });

  expect(await screen.findByRole('button', { name: /딱 3가지만/ })).toBeTruthy();
  expect(api.count('GET', '/api/v1/runtime')).toBe(1);
  expect(api.count('GET', '/api/v1/catalog/format_card')).toBe(1);
  expect(api.count('GET', '/api/v1/projects')).toBe(0);
  expect(screen.queryByText('카드를 불러오지 못했어요.')).toBeNull();
});

test('test_13_a_reload_renews_the_token_from_the_session_cookie', async () => {
  const api = await renderApp();

  expect(api.count('GET', '/api/v1/session/csrf')).toBe(1);
});

test('test_13_a_missing_session_is_told_and_the_screen_stays', async () => {
  const routes = shellRoutes();
  routes['GET /api/v1/session/csrf'] = () => ({
    status: 401,
    body: problem('unauthenticated', 'error.unauthenticated', 401),
  });

  await renderApp(routes);

  expect(
    await screen.findByText('컴퓨터 화면에 보이는 연결 코드로 다시 열어 주세요.'),
  ).toBeTruthy();
  expect(screen.getByRole('heading', { name: '한 문장으로 영상을 만들어요' })).toBeTruthy();
});

test('test_13_a_rate_limited_pairing_keeps_its_message', async () => {
  const routes = shellRoutes();
  routes['POST /api/v1/session/pair'] = () => ({
    status: 429,
    body: problem('rate_limited', 'error.rate_limited', 429),
  });

  window.location.hash = `#pair=${PAIR_CODE}`;
  await renderApp(routes);

  expect(await screen.findByText('잠시 뒤에 다시 해 주세요.')).toBeTruthy();
  expect(screen.queryByText('컴퓨터 화면에 보이는 연결 코드로 다시 열어 주세요.')).toBeNull();
});

test('test_13_an_offline_session_read_tells_the_network_problem', async () => {
  const routes = shellRoutes();
  routes['GET /api/v1/session/csrf'] = () => {
    throw new TypeError('offline');
  };

  await renderApp(routes);

  expect(await screen.findByText('서버에 연결하지 못했어요.')).toBeTruthy();
  expect(screen.queryByText('컴퓨터 화면에 보이는 연결 코드로 다시 열어 주세요.')).toBeNull();
});

test('test_13_an_expired_pair_code_asks_for_the_code_again', async () => {
  const routes = shellRoutes();
  routes['POST /api/v1/session/pair'] = () => ({
    status: 401,
    body: problem('pair_invalid', 'error.pair_invalid', 401),
  });

  window.location.hash = `#pair=${PAIR_CODE}`;
  await renderApp(routes);

  expect(
    await screen.findByText('컴퓨터 화면에 보이는 연결 코드로 다시 열어 주세요.'),
  ).toBeTruthy();
});
