import { cleanup, fireEvent, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test } from 'vitest';

import { renderEdit } from './support';

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(cleanup);

test('test_9_the_sound_effect_window_keeps_its_height_and_every_choice', async () => {
  await renderEdit();
  fireEvent.click(screen.getByRole('button', { name: '효과음 추가' }));
  const picker = await screen.findByRole('dialog', {
    name: '효과음 추가',
    description: '효과음은 요청할 때만 AI가 장면마다 두 개까지 더해요.',
  });
  const list = within(picker).getByRole('region', { name: '효과음 목록' });
  expect(list.closest('.scroll-pane')?.className).toContain('max-h-72');
  const names = Array.from(list.querySelectorAll('button')).map((button) => button.textContent);
  expect(names).toEqual(['팝', '휙', '딩', '딸깍', '반짝', '쿵', '짜잔', '보잉', '휙휙', '삐', '차임', '휘익']);
});

test('test_9_a_scene_effect_is_checked_in_its_scene_form', async () => {
  await renderEdit();
  fireEvent.click(screen.getByRole('button', { name: '효과음 추가' }));
  const picker = await screen.findByRole('dialog', { name: '효과음 추가' });
  fireEvent.click(within(picker).getByRole('button', { name: '팝' }));
  expect(await screen.findByRole('button', { name: '팝 지우기' })).toBeTruthy();
});
