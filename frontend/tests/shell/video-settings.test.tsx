import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test } from 'vitest';

import { openTab, renderEdit } from '../edit-sound/support';

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(cleanup);

async function openPanel() {
  await openTab('영상 전체');
  return document.querySelector<HTMLElement>('[data-slot="whole-panel"]')!;
}

test('scene and whole-video scopes expose only their own settings', async () => {
  await renderEdit();
  expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['이 장면', '영상 전체']);
  expect(screen.queryByText('화면 비율')).toBeNull();
  expect(screen.getByRole('heading', { name: '장면 1' })).toBeTruthy();

  const panel = within(await openPanel());
  expect(screen.queryByRole('heading', { name: '장면 1' })).toBeNull();
  expect(panel.getAllByRole('heading', { level: 3 }).map((title) => title.textContent)).toEqual(['영상', '소리', '자막']);
  expect(panel.getByText('9:16 세로')).toBeTruthy();
  expect(panel.queryByRole('combobox', { name: '화면 비율' })).toBeNull();
  expect(panel.getAllByRole('button', { name: /^목소리/ })).toHaveLength(1);
  expect(panel.getAllByRole('button', { name: /^BGM/ })).toHaveLength(1);
  expect(panel.getByRole('button', { name: /^자막 방식/ })).toBeTruthy();
  expect(panel.getByRole('combobox', { name: '글꼴' })).toBeTruthy();
});

test('the voice sheet fills the right-panel host and Escape leaves the whole scope mounted', async () => {
  await renderEdit();
  const panel = await openPanel();
  const voice = within(panel).getByRole('button', { name: /^목소리/ });
  fireEvent.click(voice);

  const card = await screen.findByRole('dialog', { name: '목소리 고르기' });
  const host = panel.closest('[data-slot="whole-picker-host"]');
  expect(host?.contains(card)).toBe(true);
  expect(panel.isConnected).toBe(true);

  fireEvent.keyDown(card, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '목소리 고르기' })).toBeNull());
  expect(panel.isConnected).toBe(true);
  expect(screen.getByRole('tab', { name: '영상 전체', selected: true })).toBeTruthy();
});

test('the saved voice is reflected in its sole whole-video field', async () => {
  await renderEdit();
  const panel = within(await openPanel());
  fireEvent.click(panel.getByRole('button', { name: /^목소리/ }));
  const card = await screen.findByRole('dialog', { name: '목소리 고르기' });
  fireEvent.click(within(card).getByRole('button', { name: '소희 (한국어)', pressed: false }));
  fireEvent.click(within(card).getByRole('button', { name: '적용' }));

  expect(await panel.findByRole('button', { name: /목소리.*소희 \(한국어\)/ })).toBeTruthy();
  await openTab('이 장면');
  expect(screen.queryByRole('button', { name: /목소리.*소희 \(한국어\)/ })).toBeNull();
});
