import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { createMockEditApi, EditApiError, type CaptionLayout, type CaptionPosition } from '@/features/edit/api';
import type { VideoView } from '@/features/edit/model';

import { openTab, pickOption, renderEdit, soundView } from './support';

const MODE_UNAVAILABLE = '현재 화면 틀에서 쓸 수 없는 자막 방식이 있어요.';
const DIGEST = '1'.repeat(64);
const LINE_IDS = ['l_0line10000000000000000000', 'l_0line20000000000000000000', 'l_0line30000000000000000000', 'l_0line40000000000000000000'];
const LINE_LABELS = ['장면 1 줄 1', '장면 1 줄 2', '장면 2 줄 1', '장면 3 줄 1'];

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(cleanup);

/** The edit fixture with a saved second layer in English and a translation on every line. */
function savedExtraView(primary: CaptionPosition, extra: CaptionPosition): VideoView {
  const view = soundView();
  view.video.settings.caption.position = primary;
  view.video.settings.caption.extra = [
    { language: 'en', mode: 'sentence', font_id: { id: 'galmuri11', revision: DIGEST }, position: extra },
  ];
  for (const scene of Object.values(view.video.scenes)) {
    scene.lines = scene.lines.map((line) => ({ ...line, extra_texts: [{ language: 'en', text: `en ${line.id.slice(-3)}` }] }));
  }
  return view;
}

async function openCaptions(view: VideoView = soundView(), api = createMockEditApi(view), someModesUnavailable = true) {
  await renderEdit(view, api);
  await openTab('자막');
  await screen.findByRole('radiogroup', { name: '자막 방식' });
  if (someModesUnavailable) await screen.findByText(MODE_UNAVAILABLE);
  return api;
}

async function chooseLanguage(name: '영어' | '한국어' | '사용 안 함') {
  const field = await screen.findByRole<HTMLButtonElement>('combobox', { name: '두 번째 언어' });
  await waitFor(() => expect(field.disabled).toBe(false));
  fireEvent.click(field);
  pickOption(await screen.findByRole('option', { name }));
}

function translationField(index: number) {
  return screen.getByRole<HTMLInputElement>('textbox', { name: `${LINE_LABELS[index]} 번역문` });
}

function fillTranslations(count = LINE_IDS.length) {
  for (let index = 0; index < count; index += 1) {
    fireEvent.change(translationField(index), { target: { value: `English ${index + 1}` } });
  }
}

async function optionsOf(name: string) {
  fireEvent.click(screen.getByRole('combobox', { name }));
  return screen.findAllByRole('option');
}

test('test_24_the_second_language_comes_from_the_catalog_and_every_line_has_a_translation_field', async () => {
  await openCaptions();
  expect(screen.queryByRole('textbox', { name: /번역문/u })).toBeNull();
  const field = await screen.findByRole<HTMLButtonElement>('combobox', { name: '두 번째 언어' });
  await waitFor(() => expect(field.disabled).toBe(false));
  const options = await optionsOf('두 번째 언어');
  expect(options.map((option) => option.textContent)).toEqual(['사용 안 함', '한국어', '영어']);
  pickOption(screen.getByRole('option', { name: '영어' }));
  await waitFor(() => expect(screen.getByRole('combobox', { name: '두 번째 언어' }).textContent).toContain('영어'));
  const translations = within(document.querySelector<HTMLElement>('[data-slot="caption-translations"]') as HTMLElement);
  for (const [index, text] of ['첫 줄', '둘째 줄', '커피를 고르는 기준은 세 가지뿐이다.', '물의 온도를 지킨다.'].entries()) {
    expect(translationField(index).value).toBe('');
    expect(translations.getByText(text)).toBeTruthy();
  }
});

test('test_24_the_second_layer_is_saved_with_its_language_font_position_and_every_translation', async () => {
  const api = await openCaptions();
  const change = vi.spyOn(api, 'change');
  await chooseLanguage('영어');
  fillTranslations();
  fireEvent.click(screen.getByRole('button', { name: '두 번째 자막 적용' }));
  await waitFor(async () =>
    expect((await api.load('v_test')).video.settings.caption.extra?.[0]?.language).toBe('en'),
  );
  expect(change).toHaveBeenCalledTimes(1);
  const ops = change.mock.calls[0]?.[1].ops ?? [];
  expect(ops[0]).toMatchObject({
    op: 'set',
    path: '/settings/caption/extra',
    value: [{ language: 'en', mode: 'sentence', font_id: { id: 'galmuri11' }, position: 'top' }],
  });
  const video = (await api.load('v_test')).video;
  const texts = video.scene_order.flatMap((id) => video.scenes[id]?.lines.map((line) => line.extra_texts?.[0]?.text) ?? []);
  expect(texts).toEqual(['English 1', 'English 2', 'English 3', 'English 4']);
  await waitFor(() => expect(screen.getByRole('combobox', { name: '두 번째 언어' }).textContent).toContain('영어'));
  expect(translationField(3).value).toBe('English 4');
});

test('test_24_a_missing_translation_blocks_the_save_and_names_the_line', async () => {
  const api = await openCaptions();
  const change = vi.spyOn(api, 'change');
  await chooseLanguage('영어');
  fillTranslations(4);
  fireEvent.change(translationField(1), { target: { value: '   ' } });
  fireEvent.click(screen.getByRole('button', { name: '두 번째 자막 적용' }));
  const issue = await screen.findByText('두 번째 자막: 번역문이 없는 줄이 있어요. 장면 1 줄 2');
  expect(issue.closest('[role="alert"]')).not.toBeNull();
  expect(screen.getByText('번역문을 적어 주세요.')).toBeTruthy();
  expect(change).not.toHaveBeenCalled();
  expect((await api.load('v_test')).video.settings.caption.extra ?? []).toEqual([]);
  fireEvent.change(translationField(1), { target: { value: 'English 2' } });
  fireEvent.click(screen.getByRole('button', { name: '두 번째 자막 적용' }));
  await waitFor(() => expect(change).toHaveBeenCalledTimes(1));
});

const SERVER_ERRORS = [
  {
    code: 'caption_overlap' as const,
    errors: [{ code: 'caption_overlap' as const, pointer: '/scenes/s_0scene1000000000000000000/lines/0' }],
    text: '첫 번째·두 번째 자막: 글이 겹쳐요. 위치나 글꼴을 바꿔 주세요.',
  },
  {
    code: 'caption_text_missing' as const,
    errors: [
      { code: 'caption_text_missing' as const, pointer: '/scenes/s_0scene1000000000000000000/lines/1/extra_texts' },
      { code: 'caption_text_missing' as const, pointer: '/scenes/s_0scene3000000000000000000/lines/0/extra_texts' },
    ],
    text: '두 번째 자막: 번역문이 없는 줄이 있어요. 장면 1 줄 2, 장면 3 줄 1',
  },
  {
    code: 'caption_mode_language' as const,
    errors: [{ code: 'caption_mode_language' as const, pointer: '/settings/caption/extra/0/mode' }],
    text: '두 번째 자막: 문장형만 쓸 수 있어요. 방식을 문장형으로 바꿔 주세요.',
  },
  {
    code: 'caption_layer_unsupported' as const,
    errors: [{ code: 'caption_layer_unsupported' as const, pointer: '/settings/caption/extra/0' }],
    text: '두 번째 자막: 이 화면 틀에서는 쓸 수 없어요. 자막을 한 겹만 받는 화면 틀이에요.',
  },
];

for (const failure of SERVER_ERRORS) {
  test(`test_24_${failure.code}_is_shown_with_its_layer_and_nothing_is_replaced`, async () => {
    const api = await openCaptions();
    vi.spyOn(api, 'change').mockRejectedValue(
      new EditApiError('invalid_combination', 422, 'error.invalid_combination', failure.errors),
    );
    await chooseLanguage('영어');
    fillTranslations();
    fireEvent.click(screen.getByRole('button', { name: '두 번째 자막 적용' }));
    const issue = await screen.findByText(failure.text);
    expect(issue.closest('[role="alert"]')).not.toBeNull();
    expect(screen.getByRole('combobox', { name: '두 번째 언어' }).textContent).toContain('영어');
    expect(screen.getByRole('combobox', { name: '두 번째 위치' }).textContent).toContain('맨 위');
    expect(translationField(0).value).toBe('English 1');
    expect((await api.load('v_test')).video.settings.caption.extra ?? []).toEqual([]);
  });
}

test('test_29_two_layers_dim_the_positions_that_overlap_and_say_why', async () => {
  const api = await openCaptions();
  await chooseLanguage('영어');
  const options = await optionsOf('자막 위치');
  const dimmed = options.filter((option) => option.getAttribute('aria-disabled') === 'true');
  expect(dimmed.map((option) => option.textContent)).toEqual(['맨 위', '위쪽', '가운데']);
  expect(options.filter((option) => option.getAttribute('aria-disabled') !== 'true').map((option) => option.textContent)).toEqual(['아래쪽', '맨 아래']);
  expect(
    screen.getByText('다른 자막(두 번째 자막 위치: 맨 위)과 두 줄이 겹치는 위치는 고를 수 없어요: 맨 위, 위쪽, 가운데'),
  ).toBeTruthy();
  const change = vi.spyOn(api, 'change');
  pickOption(screen.getByRole('option', { name: '위쪽' }));
  expect(change).not.toHaveBeenCalled();
  expect(screen.getByRole('combobox', { name: '자막 위치' }).textContent).toContain('맨 아래');
  expect((await api.load('v_test')).video.settings.caption.position).toBe('bottom');
});

test('test_29_the_second_layer_menu_dims_the_positions_next_to_the_first_caption', async () => {
  await openCaptions();
  await chooseLanguage('영어');
  const options = await optionsOf('두 번째 위치');
  expect(options.filter((option) => option.getAttribute('aria-disabled') === 'true').map((option) => option.textContent)).toEqual([
    '가운데',
    '아래쪽',
    '맨 아래',
  ]);
  expect(screen.getByText(/다른 자막\(첫 번째 자막 위치: 맨 아래\)/u)).toBeTruthy();
});

test('test_29_a_picked_position_that_became_unavailable_stays_as_it_is', async () => {
  const view = savedExtraView('middle', 'bottom');
  const api = createMockEditApi(view);
  const change = vi.spyOn(api, 'change');
  await openCaptions(view, api);
  await screen.findByText(/지금 고른 값은 그대로 두어요/u);
  expect(screen.getByText(/첫 번째·두 번째 자막: 글이 겹쳐요/u)).toBeTruthy();
  const field = screen.getByRole<HTMLButtonElement>('combobox', { name: '자막 위치' });
  expect(field.textContent).toContain('가운데');
  fireEvent.click(field);
  const current = await screen.findByRole('option', { name: '가운데' });
  expect(current.getAttribute('aria-selected')).toBe('true');
  expect(current.getAttribute('aria-disabled')).toBe('true');
  pickOption(screen.getByRole('option', { name: '아래쪽' }));
  expect(change).not.toHaveBeenCalled();
  expect(field.textContent).toContain('가운데');
  expect((await api.load('v_test')).video.settings.caption.position).toBe('middle');
  pickOption(screen.getByRole('option', { name: '위쪽' }));
  await waitFor(async () => expect((await api.load('v_test')).video.settings.caption.position).toBe('upper'));
});

test('test_29_the_result_size_and_the_dimming_come_from_the_server_layout_answer', async () => {
  const view = soundView();
  const api = createMockEditApi(view);
  const positions: CaptionPosition[] = ['top', 'upper', 'middle', 'lower', 'bottom'];
  const layout = vi.spyOn(api, 'captionLayout').mockImplementation(async (_id, query): Promise<CaptionLayout> => ({
    primary_px: 22,
    extra_px: query.extraLanguage === null ? null : 28,
    pairs: positions.flatMap((primary) =>
      positions.map((extra) => ({ primary, extra, fits: !(primary === 'upper' && extra === 'top') })),
    ),
  }));
  await openCaptions(view, api);
  expect(await screen.findByText('겹침 확인에 쓴 가장 작은 글자 크기: 22px')).toBeTruthy();
  await chooseLanguage('영어');
  expect(await screen.findByText('겹침 확인에 쓴 가장 작은 글자 크기: 첫 번째 22px, 두 번째 28px')).toBeTruthy();
  expect(layout).toHaveBeenLastCalledWith(
    'v_test',
    expect.objectContaining({ extraLanguage: 'en', extraFont: expect.objectContaining({ id: 'galmuri11' }) }),
  );
  const options = await optionsOf('자막 위치');
  expect(options.filter((option) => option.getAttribute('aria-disabled') === 'true').map((option) => option.textContent)).toEqual(['위쪽']);
});

test('test_29_a_failed_layout_read_is_said_and_never_guessed', async () => {
  const view = soundView();
  const api = createMockEditApi(view);
  vi.spyOn(api, 'captionLayout').mockRejectedValue(new EditApiError('internal', 500, ''));
  await openCaptions(view, api);
  expect(await screen.findByText('겹침 확인을 불러오지 못했어요. 저장할 때 서버가 다시 확인해요.')).toBeTruthy();
  await chooseLanguage('영어');
  const options = await optionsOf('자막 위치');
  expect(options.every((option) => option.getAttribute('aria-disabled') !== 'true')).toBe(true);
});

test('test_24_a_template_with_its_own_caption_box_says_it_takes_one_layer', async () => {
  const view = soundView();
  view.video.settings.format.layout = { id: 'dialog_stage', revision: DIGEST };
  await openCaptions(view, undefined, false);
  expect(
    await screen.findByText(
      '말풍선 화면 틀과 직접 만든 화면 틀은 자막을 한 겹만 받아요. 이 화면 틀에서는 두 번째 자막을 쓸 수 없어요.',
    ),
  ).toBeTruthy();
  await chooseLanguage('영어');
  expect(
    screen.getByText('두 번째 자막은 문장형만 써요. 대화창 타자는 첫 번째 자막에만 써요.'),
  ).toBeTruthy();
});

test('test_24_a_template_that_takes_two_layers_shows_no_layer_limit', async () => {
  await openCaptions();
  await screen.findByRole('combobox', { name: '두 번째 언어' });
  await waitFor(() => expect(screen.queryByText(/자막을 한 겹만 받아요/u)).toBeNull());
});

test('test_24_turning_the_second_layer_off_applies_at_once_and_can_be_undone', async () => {
  const view = savedExtraView('bottom', 'top');
  const api = await openCaptions(view);
  expect(await screen.findByRole('textbox', { name: '장면 1 줄 1 번역문' })).toBeTruthy();
  await chooseLanguage('사용 안 함');
  await waitFor(async () => expect((await api.load('v_test')).video.settings.caption.extra).toEqual([]));
  expect(screen.queryByRole('textbox', { name: /번역문/u })).toBeNull();
  const undo = screen.getByRole<HTMLButtonElement>('button', { name: '되돌리기' });
  await waitFor(() => expect(undo.disabled).toBe(false));
  fireEvent.click(undo);
  await waitFor(async () => expect((await api.load('v_test')).video.settings.caption.extra?.[0]?.language).toBe('en'));
  expect(await screen.findByRole('textbox', { name: '장면 1 줄 1 번역문' })).toBeTruthy();
});

test('test_24_a_saved_layer_with_a_line_that_has_no_translation_names_the_line', async () => {
  const view = savedExtraView('bottom', 'top');
  const first = view.video.scenes[view.video.scene_order[0] ?? '']?.lines[1];
  if (first !== undefined) first.extra_texts = [];
  await openCaptions(view);
  const issue = await screen.findByText('두 번째 자막: 번역문이 없는 줄이 있어요. 장면 1 줄 2');
  expect(within(issue.closest('[role="alert"]') as HTMLElement).getByText(/번역문이 없는 줄/u)).toBeTruthy();
  expect(screen.getByText('번역문을 적어 주세요.')).toBeTruthy();
});
