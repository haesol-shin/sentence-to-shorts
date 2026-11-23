import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test } from 'vitest';

import { VideoSettings } from '@/app/shell/video-settings';
import { createMockEditApi } from '@/features/edit/api';
import { EditProvider } from '@/features/edit/edit-context';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

import { soundView } from '../edit-sound/support';

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(cleanup);

async function openPanel() {
  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <EditProvider active videoId="v_test" api={createMockEditApi(soundView())}>
        <VideoSettings />
      </EditProvider>
    </LocaleProvider>,
  );
  const open = await screen.findByRole('button', { name: '영상 설정' });
  fireEvent.click(open);
  return screen.findByRole('dialog', { name: '영상 설정' });
}

test('test_10a_a_value_in_the_settings_panel_opens_its_card_over_the_panel', async () => {
  const panel = await openPanel();
  const voice = await within(panel).findByRole('button', { name: '기본 목소리' });
  fireEvent.click(voice);

  const card = await screen.findByRole('dialog', { name: '목소리 고르기' });
  expect(card).not.toBe(panel);
  // The card is modal, so the panel is behind it; it stays mounted.
  expect(panel.isConnected).toBe(true);

  // A press inside the card is not a press outside the panel.
  fireEvent.pointerDown(card);
  fireEvent.keyDown(card, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '목소리 고르기' })).toBeNull());
  expect(panel.isConnected).toBe(true);
  expect(screen.getByRole('dialog', { name: '영상 설정' })).toBe(panel);
});

test('test_10a_a_voice_picked_in_the_settings_panel_shows_in_the_panel', async () => {
  const panel = await openPanel();
  fireEvent.click(await within(panel).findByRole('button', { name: '기본 목소리' }));
  const card = await screen.findByRole('dialog', { name: '목소리 고르기' });
  fireEvent.click(within(card).getByRole('button', { name: '소희 (한국어)', pressed: false }));
  fireEvent.click(within(card).getByRole('button', { name: '적용' }));

  await waitFor(() => expect(within(panel).getByRole('button', { name: '소희 (한국어)' })).toBeTruthy());
  expect(panel.isConnected).toBe(true);
});

test('test_10a_a_press_outside_closes_the_panel_when_no_card_is_open', async () => {
  await openPanel();
  fireEvent.pointerDown(document.body);
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '영상 설정' })).toBeNull());
});
