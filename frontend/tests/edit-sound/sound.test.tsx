import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi, type Mock } from 'vitest';

import { createMockEditApi, EditApiError, type EditApi, type Job } from '@/features/edit/api';

import { openTab, pickOption, renderEdit, soundView, tagOf } from './support';

let play: Mock<() => Promise<void>>;

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  play = vi.fn(() => Promise.resolve());
  vi.spyOn(window.HTMLMediaElement.prototype, 'play').mockImplementation(play);
  vi.spyOn(window.HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function openSound(api?: EditApi) {
  const rendered = await renderEdit(undefined, api);
  await openTab('소리');
  await screen.findByRole('switch', { name: 'BGM 켜기' });
  return rendered;
}

function trackName(): string {
  return tagOf('bgm-section');
}

function composerOf(): HTMLElement {
  const plus = document.querySelector('[data-slot="composer-plus"]') as HTMLElement;
  return plus.closest('[data-slot="composer"]') as HTMLElement;
}

function chooseFile(...files: File[]) {
  const input = composerOf().querySelector<HTMLInputElement>('[data-slot="composer-file"][data-kind="bgm"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files } });
}

test('test_9_listening_to_a_voice_does_not_pick_it', async () => {
  await openSound();
  fireEvent.click(document.querySelector('[data-slot="voice-change"]') as HTMLElement);
  const dialog = await screen.findByRole('dialog', { name: '목소리 고르기' });
  const apply = within(dialog).getByRole('button', { name: '적용' }) as HTMLButtonElement;
  expect(apply.disabled).toBe(true);

  fireEvent.click(within(dialog).getByRole('button', { name: '소희 (한국어) 듣기' }));
  await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
  expect(within(dialog).getByRole('button', { name: '소희 (한국어) 듣기 멈추기' })).toBeTruthy();
  expect(apply.disabled).toBe(true);
  const rows = within(dialog).getAllByRole('button', { pressed: true });
  expect(rows).toHaveLength(1);
  expect(rows[0]?.textContent).toContain('기본 목소리');
});

test('test_9_a_voice_is_picked_with_its_own_button_and_applied_on_the_apply_button', async () => {
  await openSound();
  fireEvent.click(document.querySelector('[data-slot="voice-change"]') as HTMLElement);
  const dialog = await screen.findByRole('dialog', { name: '목소리 고르기' });
  fireEvent.click(within(dialog).getByRole('button', { name: '소희 (한국어)', pressed: false }));
  expect(tagOf('voice-section')).toBe('기본 목소리');
  fireEvent.click(within(dialog).getByRole('button', { name: '적용' }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '목소리 고르기' })).toBeNull());
  await waitFor(() => expect(tagOf('voice-section')).toBe('소희 (한국어)'));
});

test('test_9_cancel_leaves_the_voice_as_it_was', async () => {
  await openSound();
  fireEvent.click(document.querySelector('[data-slot="voice-change"]') as HTMLElement);
  const dialog = await screen.findByRole('dialog', { name: '목소리 고르기' });
  fireEvent.click(within(dialog).getByRole('button', { name: '소희 (한국어)', pressed: false }));
  fireEvent.click(within(dialog).getByRole('button', { name: '취소' }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '목소리 고르기' })).toBeNull());
  expect(tagOf('voice-section')).toBe('기본 목소리');
});

test('test_14_the_bgm_is_on_and_shows_its_mood_track_and_level', async () => {
  await openSound();
  const bgm = document.querySelector<HTMLElement>('[data-slot="bgm-section"]') as HTMLElement;
  const toggle = within(bgm).getByRole('switch', { name: 'BGM 켜기' });
  expect(toggle.getAttribute('aria-checked')).toBe('true');
  expect(within(bgm).getByRole('combobox', { name: '분위기' }).textContent).toContain('호기심');
  expect(within(bgm).getByText('궁금증 스테이지')).toBeTruthy();
  expect(within(bgm).getByRole('combobox', { name: '크기' }).textContent).toContain('보통');
  expect(within(bgm).getByRole('switch', { name: '말할 때 BGM 줄이기' }).getAttribute('aria-checked')).toBe(
    'true',
  );
});

test('test_14_the_bgm_level_has_three_choices', async () => {
  await openSound();
  fireEvent.click(screen.getByRole('combobox', { name: '크기' }));
  const options = await screen.findAllByRole('option');
  expect(options.map((option) => option.textContent)).toEqual(['작게', '보통', '크게']);
});

test('test_14_a_new_mood_picks_the_first_track_of_that_mood_in_one_change', async () => {
  const api = await openSound();
  fireEvent.click(screen.getByRole('combobox', { name: '분위기' }));
  pickOption(await screen.findByRole('option', { name: '장난스럽게' }));
  await waitFor(() => expect(trackName()).toBe('발랄한 보사노바'));
  const view = await api.load('v_test');
  expect(view.video.settings.audio.bgm.mood).toBe('playful');
  expect(view.video.settings.audio.bgm.entry?.id).toBe('playful_bossa');
  expect(view.video.revision).toBe(2);
});

test('test_14_the_bgm_switch_turns_the_bgm_off_and_the_other_controls_stop', async () => {
  await openSound();
  const bgm = document.querySelector<HTMLElement>('[data-slot="bgm-section"]') as HTMLElement;
  fireEvent.click(within(bgm).getByRole('switch', { name: 'BGM 켜기' }));
  await waitFor(() =>
    expect(within(bgm).getByRole('switch', { name: 'BGM 켜기' }).getAttribute('aria-checked')).toBe('false'),
  );
  expect((within(bgm).getByRole('combobox', { name: '크기' }) as HTMLButtonElement).disabled).toBe(true);
});

test('test_14_an_upload_that_is_not_audio_shows_an_error_and_sends_nothing', async () => {
  const api = await openSound();
  const send = vi.spyOn(api, 'uploadBgm');
  chooseFile(new File(['text'], 'notes.txt', { type: 'text/plain' }));
  expect((await screen.findByRole('alert')).textContent).toContain('오디오 파일만 올릴 수 있어요.');
  expect(send).not.toHaveBeenCalled();
});

test('test_14_a_file_dropped_during_a_bgm_job_is_refused_with_a_reason', async () => {
  const api = await openSound();
  const send = vi.spyOn(api, 'uploadBgm');
  fireEvent.click(screen.getByRole('button', { name: 'BGM 만들기' }));
  await screen.findByRole('button', { name: '멈추기' });
  const file = new File(['a'], 'late.wav', { type: 'audio/wav' });
  fireEvent.drop(composerOf(), { dataTransfer: { files: [file] } });
  expect((await screen.findByRole('alert')).textContent).toContain('BGM 작업이 끝난 뒤에 한 곡씩 올려 주세요.');
  expect(send).not.toHaveBeenCalled();
  await waitFor(() => expect(trackName()).toBe('만든 BGM 1'), { timeout: 4000 });
  expect(screen.queryByText('BGM 작업이 끝난 뒤에 한 곡씩 올려 주세요.')).toBeNull();
});

test('test_14_only_the_first_of_several_files_is_uploaded_and_the_rest_are_refused', async () => {
  const api = await openSound();
  const send = vi.spyOn(api, 'uploadBgm');
  chooseFile(
    new File(['a'], 'one.wav', { type: 'audio/wav' }),
    new File(['b'], 'two.wav', { type: 'audio/wav' }),
  );
  expect((await screen.findByRole('alert')).textContent).toContain('한 곡씩 올려 주세요.');
  expect(send).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(trackName()).toBe('올린 BGM 1'), { timeout: 4000 });
});

test('test_14_empty_files_are_rejected_locally_and_size_limits_come_from_the_server', async () => {
  const api = await openSound();
  const send = vi.spyOn(api, 'uploadBgm');
  chooseFile(new File([], 'empty.wav', { type: 'audio/wav' }));
  expect((await screen.findByRole('alert')).textContent).toContain('이 파일을 BGM으로 읽을 수 없어요.');
  expect(send).not.toHaveBeenCalled();
  send.mockRejectedValueOnce(new EditApiError('payload_too_large', 413, ''));
  chooseFile(new File(['audio'], 'large.wav', { type: 'audio/wav' }));
  expect(await screen.findByText(/파일이 너무 커요/)).toBeTruthy();
});

test('test_14_a_refused_upload_error_comes_from_the_server_answer', async () => {
  const api = await openSound();
  vi.spyOn(api, 'uploadBgm').mockRejectedValue(new EditApiError('unsupported_media', 415, ''));
  chooseFile(new File(['a'], 'a.wav', { type: 'audio/wav' }));
  expect(await screen.findByText('오디오 파일만 올릴 수 있어요.')).toBeTruthy();
});

test('test_14_an_uploaded_track_is_picked_with_its_mood', async () => {
  const api = await openSound();
  chooseFile(new File(['a'], 'mine.wav', { type: 'audio/wav' }));
  await waitFor(() => expect(trackName()).toBe('올린 BGM 1'), { timeout: 4000 });
  const view = await api.load('v_test');
  expect(view.video.settings.audio.bgm.entry?.id).toBe('upload_1');
  expect(view.video.settings.audio.bgm.mood).toBe('curious');
});

test('test_14_a_generated_loop_is_picked_after_the_job_finishes', async () => {
  await openSound();
  fireEvent.click(screen.getByRole('button', { name: 'BGM 만들기' }));
  expect(await screen.findByRole('button', { name: /멈추기/ })).toBeTruthy();
  await openTab('자막');
  await openTab('소리');
  expect(screen.getByRole('button', { name: '멈추기' })).toBeTruthy();
  await waitFor(() => expect(trackName()).toBe('만든 BGM 1'), { timeout: 4000 });
});

test('test_14_a_track_picker_lists_the_tracks_of_the_mood_and_listens_without_picking', async () => {
  await openSound();
  fireEvent.click(document.querySelector('[data-slot="bgm-change"]') as HTMLElement);
  const dialog = await screen.findByRole('dialog', { name: '호기심 곡 고르기' });
  const names = within(dialog)
    .getAllByRole('button', { pressed: false })
    .map((button) => button.textContent);
  expect(names).toContain('궁금증 선택 화면');
  fireEvent.click(within(dialog).getByRole('button', { name: '궁금증 선택 화면 듣기' }));
  await waitFor(() => expect(play).toHaveBeenCalled());
  expect(within(dialog).getByRole('button', { name: '궁금증 스테이지', pressed: true })).toBeTruthy();
});

test('test_9_a_track_without_a_server_preview_says_so', async () => {
  const api = await openSound();
  vi.spyOn(api, 'previewUrl').mockResolvedValue(null);
  fireEvent.click(document.querySelector('[data-slot="bgm-listen"]') as HTMLElement);
  expect(await screen.findByText(/미리 들을 수 없어요/)).toBeTruthy();
});

test('test_9_the_sound_effect_rule_is_written_in_the_sound_tab', async () => {
  await openSound();
  expect(
    screen.getByText('효과음은 요청할 때만 AI가 장면마다 두 개까지 더해요.'),
  ).toBeTruthy();
  expect(screen.getByText('더한 효과음은 장면 탭에서 그 장면을 골라 확인해요.')).toBeTruthy();
});

test('test_14_a_choice_survives_a_tab_switch', async () => {
  await openSound();
  fireEvent.click(screen.getByRole('combobox', { name: '크기' }));
  pickOption(await screen.findByRole('option', { name: '크게' }));
  await waitFor(() => expect(screen.getByRole('combobox', { name: '크기' }).textContent).toContain('크게'));
  await openTab('자막');
  await screen.findByRole('radiogroup', { name: '자막 방식' });
  await openTab('소리');
  expect((await screen.findByRole('combobox', { name: '크기' })).textContent).toContain('크게');
});

test('test_14_every_sound_and_caption_change_uses_a_path_the_server_accepts', async () => {
  const api = await openSound();
  const change = vi.spyOn(api, 'change');
  const accepted = /^\/settings(\/[a-z_]+)+$/u;

  fireEvent.click(screen.getByRole('switch', { name: '말할 때 BGM 줄이기' }));
  await waitFor(() => expect(change).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(screen.getByRole('switch', { name: '말할 때 BGM 줄이기' }).getAttribute('aria-checked')).toBe('false'),
  );
  fireEvent.click(screen.getByRole('combobox', { name: '크기' }));
  pickOption(await screen.findByRole('option', { name: '작게' }));
  await waitFor(() => expect(change).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole('combobox', { name: '크기' }).textContent).toContain('작게'));

  await openTab('자막');
  fireEvent.click(await screen.findByRole('radio', { name: '구절형' }));
  await waitFor(() => expect(change).toHaveBeenCalledTimes(3));

  const paths = change.mock.calls.flatMap(([, body]) =>
    body.ops.flatMap((op) => (op.op === 'set' ? [op.path] : [])),
  );
  expect(paths).toEqual(['/settings/audio/bgm', '/settings/audio/bgm', '/settings/caption/mode']);
  for (const path of paths) expect(path).toMatch(accepted);
  const bgm = change.mock.calls[1]?.[1].ops[0];
  expect(bgm?.op === 'set' ? bgm.value : null).toEqual({
    enabled: true,
    mood: 'curious',
    entry: { id: 'curious_stage_one', revision: '1'.repeat(64) },
    gain_db_x10: -200,
    ducking: false,
  });
});

test('test_14_stop_before_the_start_response_cancels_that_job', async () => {
  const api = createMockEditApi(soundView());
  const generate = api.createBgmCode.bind(api);
  let release!: (job: Job) => void;
  vi.spyOn(api, 'createBgmCode').mockReturnValue(new Promise((resolve) => { release = resolve; }));
  const cancel = vi.spyOn(api, 'cancelJob');
  await openSound(api);
  fireEvent.click(screen.getByRole('button', { name: 'BGM 만들기' }));
  fireEvent.click(screen.getByRole('button', { name: '멈추기' }));
  expect((screen.getByRole('button', { name: '멈추는 중' }) as HTMLButtonElement).disabled).toBe(true);
  const job = await generate('p_test', 'curious', null);
  release(job);
  await waitFor(() => expect(cancel).toHaveBeenCalledWith(job.id));
  await screen.findByRole('button', { name: 'BGM 만들기' });
  expect(trackName()).toBe('궁금증 스테이지');
});

test('test_14_a_failed_stop_is_reported_without_discarding_the_job', async () => {
  const api = createMockEditApi(soundView());
  vi.spyOn(api, 'cancelJob').mockRejectedValueOnce(new EditApiError('offline', 0, ''));
  await openSound(api);
  fireEvent.click(screen.getByRole('button', { name: 'BGM 만들기' }));
  fireEvent.click(screen.getByRole('button', { name: '멈추기' }));
  expect(await screen.findByText(/BGM 작업을 멈추지 못했어요/)).toBeTruthy();
  await waitFor(() => expect(trackName()).toBe('만든 BGM 1'), { timeout: 4000 });
});

test('test_14_a_completed_track_waits_for_another_setting_write', async () => {
  const api = createMockEditApi(soundView());
  const change = api.change.bind(api);
  let release!: () => void;
  const blocked = new Promise<void>((resolve) => { release = resolve; });
  const write = vi.spyOn(api, 'change').mockImplementationOnce(async (id, body) => {
    await blocked;
    return change(id, body);
  });
  await openSound(api);
  fireEvent.click(screen.getByRole('button', { name: 'BGM 만들기' }));
  await openTab('자막');
  fireEvent.click(screen.getByRole('radio', { name: '구절형' }));
  await openTab('소리');
  expect(await screen.findByText('지금 변경이 끝나면 새 곡을 적용해요.', {}, { timeout: 4000 })).toBeTruthy();
  expect(trackName()).toBe('궁금증 스테이지');
  release();
  await waitFor(() => expect(trackName()).toBe('만든 BGM 1'));
  expect((await api.load('v_test')).video.settings.caption.mode).toBe('phrase');
  expect(write).toHaveBeenCalledTimes(2);
});

test('test_14_failed_and_incomplete_catalogs_keep_the_saved_pair_until_reloaded', async () => {
  const api = createMockEditApi(soundView());
  const allTracks = await api.listBgm('v_test');
  vi.spyOn(api, 'listBgm')
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce(allTracks.filter((track) => track.mood === 'curious'));
  await openSound(api);
  const mood = screen.getByRole('combobox', { name: '분위기' });
  expect(await screen.findByText('곡 목록을 불러오지 못했어요.')).toBeTruthy();
  expect((mood as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '곡 목록 다시 불러오기' }));
  await waitFor(() => expect((mood as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(mood);
  pickOption(await screen.findByRole('option', { name: '장난스럽게' }));
  expect(await screen.findByText('이 분위기의 곡이 아직 없어요.')).toBeTruthy();
  const unchanged = (await api.load('v_test')).video.settings.audio.bgm;
  expect([unchanged.mood, unchanged.entry?.id]).toEqual(['curious', 'curious_stage_one']);
  fireEvent.click(screen.getByRole('button', { name: '곡 목록 다시 불러오기' }));
  await waitFor(() => expect((mood as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(mood);
  pickOption(await screen.findByRole('option', { name: '장난스럽게' }));
  await waitFor(() => expect(trackName()).toBe('발랄한 보사노바'));
});

test('test_14_sound_undo_does_not_require_leaving_the_tab', async () => {
  await openSound();
  const toggle = screen.getByRole('switch', { name: 'BGM 켜기' });
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'));
  const undo = screen.getByRole('button', { name: '되돌리기' }) as HTMLButtonElement;
  await waitFor(() => expect(undo.disabled).toBe(false));
  fireEvent.click(undo);
  await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));
});
