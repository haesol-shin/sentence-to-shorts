import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import {
  DRAFT_JOB_PATH,
  DRAFT_VIDEO_PATH,
  draftJob,
  shellRoutes,
  type Answer,
  type RouteHandler,
} from '../support/api';
import { COMPOSER_LABEL, renderApp, sendSentence } from '../support/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const KEY_LABEL = 'Claude API key';
const PUT_PATH = 'PUT /api/v1/credentials/llm';

type Runtime = { profile: string; llm_auth: { adapter: string; state: string } };

/** The runtime the shell routes answer, with the profile, adapter and key state swapped in. */
function routesWith(
  profile: string,
  state: string | (() => string),
  extra: Record<string, RouteHandler> = {},
  adapter = 'anthropic_api',
): Record<string, RouteHandler> {
  const routes = shellRoutes();
  const base = routes['GET /api/v1/runtime'];
  routes['GET /api/v1/runtime'] = async (call) => {
    const answer = await base(call);
    const runtime = answer.body as Runtime;
    return {
      ...answer,
      body: {
        ...runtime,
        profile,
        llm_auth: { adapter, state: typeof state === 'string' ? state : state() },
      },
    };
  };
  return { ...routes, ...extra };
}

function problem(status: number, code: string, messageKey: string): Answer {
  return {
    status,
    body: { type: 'about:blank', title: code, status, code, message_key: messageKey, retryable: false },
  };
}

test('test_release_missing_key_shows_the_key_block_with_a_masked_field', async () => {
  await renderApp(routesWith('release', 'missing'));

  const field = await screen.findByLabelText(KEY_LABEL);
  expect(field.getAttribute('type')).toBe('password');
  expect(screen.getByRole('button', { name: '저장' })).toBeTruthy();
  // The hint names the service and where its key comes from, not only where it is kept.
  const hint = screen.getByText(/OS 키 저장소에만 보관돼요/u);
  expect(hint.textContent).toContain('console.anthropic.com');
});

test('test_release_expired_key_shows_the_key_block', async () => {
  await renderApp(routesWith('release', 'expired'));

  expect(await screen.findByLabelText(KEY_LABEL)).toBeTruthy();
});

test('test_dev_on_the_cli_never_shows_the_key_block', async () => {
  const api = await renderApp(routesWith('dev', 'missing', {}, 'claude_cli'));

  await waitFor(() => expect(api.count('GET', '/api/v1/runtime')).toBeGreaterThan(0));
  await screen.findByRole('button', { name: /딱 3가지만/ });
  expect(screen.queryByLabelText(KEY_LABEL)).toBeNull();
});

test('test_dev_on_the_api_shows_the_key_block_when_the_key_is_missing', async () => {
  await renderApp(routesWith('dev', 'missing'));

  const field = await screen.findByLabelText(KEY_LABEL);
  expect(field.getAttribute('type')).toBe('password');
});

test('test_dev_on_the_api_with_a_usable_key_hides_the_key_block', async () => {
  await renderApp(routesWith('dev', 'ok'));

  await screen.findByRole('button', { name: /딱 3가지만/ });
  expect(screen.queryByLabelText(KEY_LABEL)).toBeNull();
});

test('test_release_with_a_usable_key_hides_the_key_block', async () => {
  await renderApp(routesWith('release', 'ok'));

  await screen.findByRole('button', { name: /딱 3가지만/ });
  expect(screen.queryByLabelText(KEY_LABEL)).toBeNull();
});

test('test_saving_the_key_sends_it_and_reads_the_runtime_again', async () => {
  let state = 'missing';
  const api = await renderApp(
    routesWith('release', () => state, {
      [PUT_PATH]: () => {
        state = 'ok';
        return { status: 204 };
      },
    }),
  );

  fireEvent.change(await screen.findByLabelText(KEY_LABEL), { target: { value: ' sk-test-key ' } });
  fireEvent.click(screen.getByRole('button', { name: '저장' }));

  await waitFor(() => expect(screen.queryByLabelText(KEY_LABEL)).toBeNull());
  expect(screen.getByText('키를 저장했어요. 이제 문장을 보내면 돼요.')).toBeTruthy();
  const put = api.calls.find((call) => call.method === 'PUT' && call.path === '/api/v1/credentials/llm');
  expect(put?.body).toEqual({ api_key: 'sk-test-key' });
  expect(api.count('GET', '/api/v1/runtime')).toBeGreaterThanOrEqual(2);
});

test('test_a_rejected_key_shows_the_field_error_and_keeps_the_block', async () => {
  await renderApp(
    routesWith('release', 'missing', {
      [PUT_PATH]: () => problem(400, 'validation_failed', 'error.validation_failed'),
    }),
  );

  fireEvent.change(await screen.findByLabelText(KEY_LABEL), { target: { value: 'bad' } });
  fireEvent.click(screen.getByRole('button', { name: '저장' }));

  expect(await screen.findByText('키 형식이 맞지 않아요. 다시 붙여 넣어 주세요.')).toBeTruthy();
  expect(screen.getByLabelText(KEY_LABEL).getAttribute('aria-invalid')).toBe('true');
});

test('test_a_remote_browser_is_told_the_key_is_entered_on_this_computer_only', async () => {
  await renderApp(
    routesWith('release', 'missing', {
      [PUT_PATH]: () => problem(403, 'loopback_only', 'error.forbidden_origin'),
    }),
  );

  fireEvent.change(await screen.findByLabelText(KEY_LABEL), { target: { value: 'sk-test-key' } });
  fireEvent.click(screen.getByRole('button', { name: '저장' }));

  expect(await screen.findByText('키는 이 컴퓨터에서만 입력할 수 있어요.')).toBeTruthy();
});

test('test_a_refused_draft_brings_the_block_back_and_keeps_the_sentence', async () => {
  await renderApp(
    routesWith('release', 'ok', {
      [`POST ${DRAFT_VIDEO_PATH}/draft`]: () =>
        problem(503, 'llm_auth_required', 'error.llm_auth_required'),
    }),
  );

  sendSentence('커피를 고르는 세 가지 기준');

  expect(await screen.findByLabelText(KEY_LABEL)).toBeTruthy();
  expect(screen.getByText('모델 연결을 먼저 확인해 주세요.')).toBeTruthy();
  expect((screen.getByRole('textbox', { name: COMPOSER_LABEL }) as HTMLTextAreaElement).value).toBe(
    '커피를 고르는 세 가지 기준',
  );
});

test('test_a_draft_job_that_fails_with_llm_auth_returns_to_the_block', async () => {
  await renderApp(
    routesWith('release', 'ok', {
      [`GET ${DRAFT_JOB_PATH}`]: () => ({
        status: 200,
        body: {
          ...draftJob,
          state: 'failed',
          error: { code: 'llm_auth', detail: {}, retryable: false, scene_id: null, stage: null },
        },
      }),
    }),
  );

  sendSentence('커피를 고르는 세 가지 기준');

  expect(await screen.findByLabelText(KEY_LABEL)).toBeTruthy();
  expect(screen.getByText('모델 연결을 먼저 확인해 주세요.')).toBeTruthy();
  expect((screen.getByRole('textbox', { name: COMPOSER_LABEL }) as HTMLTextAreaElement).value).toBe(
    '커피를 고르는 세 가지 기준',
  );
});

test('test_dev_on_the_cli_keeps_the_header_error_for_a_refused_draft', async () => {
  await renderApp(
    routesWith(
      'dev',
      'ok',
      {
        [`POST ${DRAFT_VIDEO_PATH}/draft`]: () =>
          problem(503, 'llm_auth_required', 'error.llm_auth_required'),
      },
      'claude_cli',
    ),
  );

  sendSentence('커피를 고르는 세 가지 기준');

  expect(await screen.findByText('모델 연결을 먼저 확인해 주세요.')).toBeTruthy();
  expect(screen.queryByLabelText(KEY_LABEL)).toBeNull();
});

test('test_a_refused_draft_in_dev_on_the_api_brings_the_block_back', async () => {
  await renderApp(
    routesWith('dev', 'ok', {
      [`POST ${DRAFT_VIDEO_PATH}/draft`]: () =>
        problem(503, 'llm_auth_required', 'error.llm_auth_required'),
    }),
  );

  sendSentence('커피를 고르는 세 가지 기준');

  expect(await screen.findByLabelText(KEY_LABEL)).toBeTruthy();
  expect(screen.getByText('모델 연결을 먼저 확인해 주세요.')).toBeTruthy();
  expect((screen.getByRole('textbox', { name: COMPOSER_LABEL }) as HTMLTextAreaElement).value).toBe(
    '커피를 고르는 세 가지 기준',
  );
});

test('test_an_unread_runtime_keeps_the_header_error_for_a_refused_draft', async () => {
  await renderApp(
    routesWith('release', 'missing', {
      'GET /api/v1/runtime': () => ({ status: 500 }),
      [`POST ${DRAFT_VIDEO_PATH}/draft`]: () =>
        problem(503, 'llm_auth_required', 'error.llm_auth_required'),
    }),
  );

  sendSentence('커피를 고르는 세 가지 기준');

  expect(await screen.findByText('모델 연결을 먼저 확인해 주세요.')).toBeTruthy();
  expect(screen.queryByLabelText(KEY_LABEL)).toBeNull();
});
