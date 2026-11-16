import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, expect, test, vi } from 'vitest';

import { FirstScreen } from '@/app/first-screen';
import type { Attachment } from '@/features/concept/types';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

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

test('test_10a_first_screen_offers_real_language_and_length_values', async () => {
  await renderApp();

  const language = screen.getByLabelText('영상 언어') as HTMLSelectElement;
  const duration = screen.getByLabelText('영상 길이') as HTMLSelectElement;
  expect(language.value).toBe('ko');
  expect(duration.value).toBe('60');

  fireEvent.change(language, { target: { value: 'en' } });
  fireEvent.change(duration, { target: { value: '120' } });

  expect(language.value).toBe('en');
  expect(duration.value).toBe('120');
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

function FirstScreenHarness({
  onSubmit,
}: {
  onSubmit: (text: string, attachments: Attachment[]) => void;
}) {
  const [draft, setDraft] = useState('원두 이야기');
  return (
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <FirstScreen
        draft={draft}
        card={null}
        submitting={false}
        ready={false}
        onDraftChange={setDraft}
        onPickCard={() => undefined}
        onClearCard={() => undefined}
        onSubmit={onSubmit}
      />
    </LocaleProvider>
  );
}

test('test_10a_text_contents_reach_the_start_boundary_with_the_sentence', async () => {
  const onSubmit = vi.fn();
  render(<FirstScreenHarness onSubmit={onSubmit} />);

  const fileInput = document.querySelector<HTMLInputElement>(
    'input[type="file"][data-kind="text"]',
  );
  expect(fileInput).not.toBeNull();
  if (fileInput === null) return;
  fireEvent.change(fileInput, {
    target: {
      files: [new File(['원두는 신선도가 중요하다.'], 'notes.md', { type: 'text/markdown' })],
    },
  });
  await waitFor(() =>
    expect(document.querySelectorAll('[data-slot="composer-attachment"]')).toHaveLength(1),
  );

  fireEvent.click(screen.getByRole('button', { name: '보내기' }));

  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  const [text, attachments] = onSubmit.mock.calls[0] as [string, Attachment[]];
  expect(text).toBe('원두 이야기');
  expect(attachments).toHaveLength(1);
  expect(attachments[0]).toMatchObject({
    kind: 'text',
    name: 'notes.md',
    text: '원두는 신선도가 중요하다.',
  });
});
