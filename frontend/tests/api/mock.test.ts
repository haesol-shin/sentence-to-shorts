import { expect, test } from 'vitest';

import { installMockApi, mockFixtureCount, mockResponse } from '@/shared/api/mock';
import { getCsrfToken, pairSession } from '@/shared/api/client';
import { resetSession } from '@/shared/lib/session';

test('test_6_mock_mode_answers_from_the_recorded_fixtures', () => {
  expect(mockFixtureCount).toBeGreaterThan(40);

  expect(mockResponse({ method: 'GET', path: '/session/csrf' })).toMatchObject({ status: 200 });
  expect(mockResponse({ method: 'GET', path: '/runtime' })).toMatchObject({ status: 200 });
  expect(mockResponse({ method: 'GET', path: '/catalog/format_card' })).toMatchObject({
    status: 200,
  });
  expect(mockResponse({ method: 'POST', path: '/videos/v_1/draft' })).toMatchObject({
    status: 202,
  });
  expect(mockResponse({ method: 'GET', path: '/videos/v_1/revisions' })).toMatchObject({
    status: 200,
  });
});

test('test_6_mock_mode_leaves_an_unrecorded_call_unanswered', () => {
  expect(mockResponse({ method: 'DELETE', path: '/nothing/here' })).toEqual({
    status: 404,
    headers: {},
    body: null,
  });
});

test('test_13_mock_mode_pairing_hands_a_token_to_the_client', async () => {
  resetSession();
  installMockApi();

  const paired = await pairSession('paircode-0123456789');

  expect(paired.ui_language).toBe('ko');
  expect(getCsrfToken()).toBe(paired.csrf_token);
});
