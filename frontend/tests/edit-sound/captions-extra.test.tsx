import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { createMockEditApi } from '@/features/edit/api';

import { openCaptionMode, openTab, pickOption, renderEdit, soundView } from './support';

afterEach(cleanup);

const font = { id: 'galmuri11', revision: '1'.repeat(64) };

test('legacy second captions are kept but cannot be edited from the whole-video panel', async () => {
  const view = soundView();
  view.video.settings.caption.extra = [{ language: 'en', mode: 'sentence', font_id: font, position: 'top' }];
  for (const scene of Object.values(view.video.scenes)) {
    scene.lines = scene.lines.map((line) => ({ ...line, extra_texts: [{ language: 'en', text: 'Caption' }] }));
  }

  const api = createMockEditApi(view);
  const change = vi.spyOn(api, 'change');
  const catalog = vi.spyOn(api, 'listCatalog');
  await renderEdit(view, api);
  await openTab('영상 전체');
  const dialog = within(await openCaptionMode());
  expect(dialog.queryByText(/두 번째 자막/)).toBeNull();
  expect(dialog.queryByRole('textbox')).toBeNull();
  expect(catalog.mock.calls.some(([kind]) => kind === 'caption_language')).toBe(false);
  expect(await dialog.findByText('겹침 확인에 쓴 가장 작은 글자 크기: 22px')).toBeTruthy();

  fireEvent.click(dialog.getByRole('radio', { name: '구절형' }));
  await waitFor(async () => expect((await api.load('v_test')).video.settings.caption.mode).toBe('phrase'));
  const saved = (await api.load('v_test')).video;
  expect(saved.settings.caption.extra).toEqual(view.video.settings.caption.extra);
  expect(saved.scenes).toEqual(view.video.scenes);
  expect(change.mock.calls[0]?.[1].ops).toEqual([
    { op: 'set', path: '/settings/caption/mode', value: 'phrase', origin: 'user' },
  ]);
});

test('the primary layout still marks positions outside the safe area unavailable', async () => {
  const view = soundView();
  const api = createMockEditApi(view);
  vi.spyOn(api, 'captionLayout').mockResolvedValue({
    primary_px: 22,
    extra_px: null,
    pairs: [{ primary: 'top', extra: 'top', fits: false }],
  });
  await renderEdit(view, api);
  await openTab('영상 전체');
  const dialog = within(await openCaptionMode());
  expect(await dialog.findByText(/안전 영역에 들어가지 않아 고를 수 없는 위치/)).toBeTruthy();
  fireEvent.click(dialog.getByRole('combobox', { name: '자막 위치' }));
  const option = await screen.findByRole('option', { name: '맨 위' });
  expect(option.getAttribute('aria-disabled')).toBe('true');
  pickOption(option);
  expect((await api.load('v_test')).video.settings.caption.position).toBe('bottom');
});
