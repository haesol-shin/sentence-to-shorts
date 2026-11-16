import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { renderApp, sendSentence } from '../support/render';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('test_10a_sidebar_names_an_icon_on_hover', async () => {
  await renderApp();
  const icon = screen.getByRole('button', { name: '새 영상' });

  expect(screen.queryByRole('tooltip')).toBeNull();

  fireEvent.pointerOver(icon);
  expect((await screen.findByRole('tooltip')).textContent).toContain('새 영상');

  fireEvent.pointerOut(icon);
  await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull());
});

test('test_10a_sidebar_names_an_icon_on_keyboard_focus', async () => {
  await renderApp();
  const icon = screen.getByRole('button', { name: '새 영상' });

  icon.focus();

  expect((await screen.findByRole('tooltip')).textContent).toContain('새 영상');
});

test('test_10a_first_screen_shows_no_step_indicator', async () => {
  await renderApp();

  expect(document.querySelector('[data-slot="stage-indicator"]')).toBeNull();
  expect(document.querySelector('[data-slot="stage-menu"]')).toBeNull();
});

test('test_10a_step_indicator_appears_only_on_the_edit_screen', async () => {
  await renderApp();
  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  expect(document.querySelector('[data-slot="stage-indicator"]')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '단계 열기' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '편집' }));

  const indicator = document.querySelector('[data-slot="stage-indicator"]');
  expect(indicator).not.toBeNull();
  expect(indicator?.querySelector('[aria-current="step"]')?.textContent).toBe('편집');

  fireEvent.click(screen.getByRole('button', { name: '단계 열기' }));
  fireEvent.click(screen.getByRole('menuitem', { name: '내보내기' }));

  expect(document.querySelector('[data-slot="stage-indicator"]')).toBeNull();
});

test('test_10a_the_next_action_keeps_its_seat_on_stage_screens', async () => {
  await renderApp();
  expect(document.querySelector('[data-slot="next-action"]')).toBeNull();

  sendSentence('커피를 고르는 세 가지 기준');
  await screen.findByRole('heading', { name: '컨셉' });

  const action = document.querySelector<HTMLButtonElement>('[data-slot="next-action"]');
  expect(action?.disabled).toBe(true);
});

test('test_10a_brand_name_comes_from_the_runtime_answer', async () => {
  await renderApp();
  await waitFor(() =>
    expect(document.querySelector('[data-slot="brand"]')?.textContent).toBe('테스트 앱'),
  );
});
