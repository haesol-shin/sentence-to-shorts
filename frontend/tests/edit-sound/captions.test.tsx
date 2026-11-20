import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { createMockEditApi } from '@/features/edit/api';

import { openTab, pickOption, renderEdit, soundView } from './support';

const MODE_UNAVAILABLE = '현재 화면 틀에서 쓸 수 없는 자막 방식이 있어요.';

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(cleanup);

async function openCaptions() {
  const api = await renderEdit();
  await openTab('자막');
  await screen.findByRole('radiogroup', { name: '자막 방식' });
  await screen.findByText(MODE_UNAVAILABLE);
  return api;
}

test('test_24_the_caption_mode_is_one_of_three_fixed_choices', async () => {
  await openCaptions();
  const group = screen.getByRole('radiogroup', { name: '자막 방식' });
  const radios = Array.from(group.querySelectorAll('[role="radio"]'));
  expect(radios).toHaveLength(3);
  expect(group.textContent).toContain('문장형');
  expect(group.textContent).toContain('구절형');
  expect(group.textContent).toContain('대화창 타자');
  expect(radios.filter((radio) => radio.getAttribute('aria-checked') === 'true')).toHaveLength(1);
  expect(screen.getByRole('radio', { name: '문장형' }).getAttribute('aria-checked')).toBe('true');
  const unavailable = screen.getByRole('radio', { name: '대화창 타자' });
  expect(unavailable.hasAttribute('data-disabled')).toBe(true);
  fireEvent.click(unavailable);
  expect(unavailable.getAttribute('aria-checked')).toBe('false');
});

test('test_24_picking_a_mode_changes_the_video_and_survives_a_tab_switch', async () => {
  const api = await openCaptions();
  fireEvent.click(screen.getByRole('radio', { name: '구절형' }));
  await waitFor(() =>
    expect(screen.getByRole('radio', { name: '구절형' }).getAttribute('aria-checked')).toBe('true'),
  );
  expect((await api.load('v_test')).video.settings.caption.mode).toBe('phrase');
  await openTab('소리');
  await screen.findByRole('switch', { name: 'BGM 켜기' });
  await openTab('자막');
  expect((await screen.findByRole('radio', { name: '구절형' })).getAttribute('aria-checked')).toBe('true');
});

test('test_24_typewriter_can_be_selected_when_the_template_allows_it', async () => {
  const view = soundView();
  const api = createMockEditApi(view);
  vi.spyOn(api, 'templateCaptionModes').mockResolvedValue(['sentence', 'typewriter']);
  await renderEdit(view, api);
  await openTab('자막');
  await screen.findByText(MODE_UNAVAILABLE);
  const typewriter = screen.getByRole('radio', { name: '대화창 타자' });
  const phrase = screen.getByRole('radio', { name: '구절형' });
  expect(typewriter.getAttribute('aria-disabled')).toBeNull();
  expect(phrase.getAttribute('aria-disabled')).toBe('true');
  fireEvent.click(typewriter);
  await waitFor(() => expect(typewriter.getAttribute('aria-checked')).toBe('true'));
  expect((await api.load('v_test')).video.settings.caption.mode).toBe('typewriter');
});

test('test_24_the_caption_position_has_five_choices', async () => {
  await openCaptions();
  const field = screen.getByRole('combobox', { name: '자막 위치' });
  expect(field.textContent).toContain('맨 아래');
  fireEvent.click(field);
  const options = await screen.findAllByRole('option');
  expect(options.map((option) => option.textContent)).toEqual([
    '맨 위',
    '위쪽',
    '가운데',
    '아래쪽',
    '맨 아래',
  ]);
});

test('test_24_a_new_position_is_written_to_the_video_and_kept_after_a_tab_switch', async () => {
  const api = await openCaptions();
  fireEvent.click(screen.getByRole('combobox', { name: '자막 위치' }));
  pickOption(await screen.findByRole('option', { name: '위쪽' }));
  await waitFor(() =>
    expect(screen.getByRole('combobox', { name: '자막 위치' }).textContent).toContain('위쪽'),
  );
  expect((await api.load('v_test')).video.settings.caption.position).toBe('upper');
  await openTab('장면');
  await screen.findByRole('heading', { name: '장면 1' });
  await openTab('자막');
  expect((await screen.findByRole('combobox', { name: '자막 위치' })).textContent).toContain('위쪽');
});

test('test_24_the_caption_font_is_picked_from_the_catalog', async () => {
  const api = await openCaptions();
  const field = screen.getByRole('combobox', { name: '글꼴' });
  expect(field.textContent).toContain('갈무리 11');
  fireEvent.click(field);
  const options = await screen.findAllByRole('option');
  expect(options.map((option) => option.textContent)).toEqual(['갈무리 11', '갈무리 14']);
  pickOption(screen.getByRole('option', { name: '갈무리 14' }));
  await waitFor(async () =>
    expect((await api.load('v_test')).video.settings.caption.font_id.id).toBe('galmuri14'),
  );
});

test('test_24_an_incompatible_font_stays_selected_but_cannot_be_chosen', async () => {
  const view = soundView();
  const api = createMockEditApi(view);
  vi.spyOn(api, 'styleOptions').mockResolvedValue({
    backgrounds: [],
    expressions: [],
    fonts: ['galmuri14'],
  });
  await renderEdit(view, api);
  await openTab('자막');
  expect(await screen.findByText('현재 그림체에서 쓸 수 없는 글꼴이 있어요.')).toBeTruthy();
  const field = screen.getByRole<HTMLButtonElement>('combobox', { name: '글꼴' });
  expect(field.textContent).toContain('갈무리 11');
  fireEvent.click(field);
  const current = await screen.findByRole('option', { name: '갈무리 11' });
  expect(current.getAttribute('aria-selected')).toBe('true');
  expect(current.getAttribute('aria-disabled')).toBe('true');
  pickOption(screen.getByRole('option', { name: '갈무리 14' }));
  await waitFor(() => {
    expect(field.disabled).toBe(false);
    expect(field.textContent).toContain('갈무리 14');
  });
  expect((await api.load('v_test')).video.settings.caption.font_id.id).toBe('galmuri14');
  fireEvent.click(field);
  const unavailable = await screen.findByRole('option', { name: '갈무리 11' });
  const change = vi.spyOn(api, 'change');
  pickOption(unavailable);
  expect(change).not.toHaveBeenCalled();
  expect(field.textContent).toContain('갈무리 14');
});

test('test_24_missing_compatibility_keeps_current_mode_and_font', async () => {
  const view = soundView();
  const api = createMockEditApi(view);
  vi.spyOn(api, 'styleOptions').mockRejectedValue(new Error('manifest unavailable'));
  const change = vi.spyOn(api, 'change');
  await renderEdit(view, api);
  await openTab('자막');
  expect(await screen.findByText('자막 선택지를 불러오지 못했어요.')).toBeTruthy();
  const current = screen.getByRole('radio', { name: '문장형' });
  expect(current.getAttribute('aria-checked')).toBe('true');
  const phrase = screen.getByRole('radio', { name: '구절형' });
  expect(phrase.hasAttribute('data-disabled')).toBe(true);
  fireEvent.click(phrase);
  const field = screen.getByRole<HTMLButtonElement>('combobox', { name: '글꼴' });
  expect(field.textContent).toContain('갈무리 11');
  expect(field.disabled).toBe(true);
  fireEvent.click(field);
  expect(screen.queryByRole('listbox')).toBeNull();
  expect(change).not.toHaveBeenCalled();
});

test('test_24_leaving_typewriter_drops_the_typing_sound_and_caption_undo_restores_both', async () => {
  const view = soundView();
  view.video.settings.caption.mode = 'typewriter';
  const typingSound = { id: 'keys', revision: '1'.repeat(64) };
  view.video.settings.caption.typing_sound = typingSound;
  const api = await renderEdit(view);
  await openTab('자막');
  await screen.findByText(MODE_UNAVAILABLE);
  const undo = screen.getByRole<HTMLButtonElement>('button', { name: '되돌리기' });
  expect(undo.disabled).toBe(true);
  const current = screen.getByRole('radio', { name: '대화창 타자' });
  expect(current.getAttribute('aria-checked')).toBe('true');
  expect(current.hasAttribute('data-disabled')).toBe(true);
  fireEvent.click(await screen.findByRole('radio', { name: '문장형' }));
  await waitFor(async () => {
    const caption = (await api.load('v_test')).video.settings.caption;
    expect(caption.mode).toBe('sentence');
    expect(caption.typing_sound).toBeNull();
  });
  await waitFor(() => expect(undo.disabled).toBe(false));
  const undoRequest = vi.spyOn(api, 'undo');
  fireEvent.click(undo);
  await waitFor(() => {
    expect(current.getAttribute('aria-checked')).toBe('true');
    expect(undo.disabled).toBe(true);
  });
  expect((await api.load('v_test')).video.settings.caption.typing_sound).toEqual(typingSound);
  fireEvent.click(undo);
  expect(undoRequest).toHaveBeenCalledTimes(1);
});
