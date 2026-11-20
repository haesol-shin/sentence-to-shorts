import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';

import { createMockEditApi, type ChangeOp, type EditApi } from '@/features/edit/api';
import { ChangeReview } from '@/features/edit/change-review';
import { EditProvider, useEdit } from '@/features/edit/edit-context';
import type { VideoView } from '@/features/edit/model';
import { BGM_PATH, VOICE_PATH } from '@/features/edit/sound/model';
import { translate } from '@/shared/lib/i18n/catalog';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

import { soundView } from './support';

afterEach(cleanup);

const revision = '2'.repeat(64);

function Review() {
  const edit = useEdit();
  return <ChangeReview edit={edit} />;
}

async function renderPending(
  ops: ChangeOp[],
  {
    language = 'ko',
    view = soundView(),
    api = createMockEditApi(view),
  }: { language?: 'ko' | 'en'; view?: VideoView; api?: EditApi } = {},
) {
  const plan = await api.change(view.video.id, {
    base_revision: view.video.revision,
    source: 'direct',
    target: { scene_id: null, pointer: null },
    ops,
  });
  api.load = async () => ({ ...view, pending_change: plan.id });
  api.readChange = async () => ({
    ...plan, requires_confirmation: true, status: 'proposed', applied_revision: null,
  });
  render(
    <LocaleProvider language={language} setLanguage={() => undefined}>
      <EditProvider active videoId={view.video.id} api={api}>
        <Review />
      </EditProvider>
    </LocaleProvider>,
  );
  return screen.findByRole('dialog', { name: translate(language, 'edit.change.editTitle') });
}

function expectRows(dialog: HTMLElement, expected: readonly (readonly string[])[]) {
  const rows = within(dialog).getAllByRole('listitem');
  expect(rows.map((row) => Array.from(row.children, (cell) => cell.textContent?.trim()))).toEqual(expected);
}

test.each([
  {
    language: 'ko',
    rows: [
      ['목소리', '기본 목소리 →', '소희 (한국어)'],
      ['분위기', '호기심 →', '차분하게'],
      ['곡', '궁금증 스테이지 →', '차분한 자장가'],
    ],
  },
  {
    language: 'en',
    rows: [
      ['Voice', 'Default voice →', 'Sohee (Korean)'],
      ['Mood', 'Curious →', 'Calm'],
      ['Track', 'Curious stage →', 'Calm lullaby'],
    ],
  },
] as const)('test_14_pending_audio_choices_use_catalog_labels_for_$language', async ({ language, rows }) => {
  const view = soundView();
  const dialog = await renderPending([
    { op: 'set', path: VOICE_PATH, value: { id: 'sohee_ko', revision }, origin: 'user' },
    {
      op: 'set', path: BGM_PATH, origin: 'user',
      value: { ...view.video.settings.audio.bgm, mood: 'calm', entry: { id: 'calm_happy_lullaby', revision } },
    },
  ], { language, view });

  await waitFor(() => expectRows(dialog, rows));
  expect(dialog.textContent).not.toMatch(/fixed_wav|sohee_ko|curious_stage_one|calm_happy_lullaby|[0-9]{64}/);
});

test('test_14_a_pending_bgm_compares_changed_fields_separately', async () => {
  const view = soundView();
  const dialog = await renderPending([{
    op: 'set', path: BGM_PATH, origin: 'user',
    value: { ...view.video.settings.audio.bgm, enabled: false, gain_db_x10: -155, ducking: false },
  }], { view });

  expectRows(dialog, [
    ['BGM 켜기', '켜짐 →', '꺼짐'],
    ['크기', '보통 →', '-15.5 dB'],
    ['말할 때 BGM 줄이기', '켜짐 →', '꺼짐'],
  ]);
});

test('test_14_unknown_catalog_labels_use_a_localized_fallback', async () => {
  const view = soundView();
  const api = createMockEditApi(view);
  const tracks = await api.listBgm(view.video.id);
  api.listBgm = async () => tracks.map((track) => track.id === 'curious_stage_select'
    ? { ...track, label: { ...track.label, ko: '' } }
    : track);
  const dialog = await renderPending([
    { op: 'set', path: VOICE_PATH, value: { id: 'missing_voice', revision }, origin: 'user' },
    { op: 'set', path: `${BGM_PATH}/entry`, value: { id: 'curious_stage_select', revision }, origin: 'user' },
  ], { view, api });

  const unknown = translate('ko', 'audio.review.unknown');
  expect(unknown).not.toBe('audio.review.unknown');
  await waitFor(() => expectRows(dialog, [
    ['목소리', '기본 목소리 →', unknown],
    ['곡', '궁금증 스테이지 →', unknown],
  ]));
  expect(dialog.textContent).not.toMatch(/missing_voice|curious_stage_select|[0-9]{64}/);
});

test('test_14_caption_changes_show_names_and_never_paths_or_revisions', async () => {
  const dialog = await renderPending([
    { op: 'set', path: '/settings/caption/mode', value: 'phrase', origin: 'user' },
    { op: 'set', path: '/settings/caption/position', value: 'top', origin: 'user' },
    { op: 'set', path: '/settings/caption/font_id', value: { id: 'galmuri14', revision }, origin: 'user' },
    { op: 'set', path: '/settings/caption/highlight', value: false, origin: 'user' },
  ]);

  await waitFor(() => expectRows(dialog, [
    ['자막 방식', '문장형 →', '구절형'],
    ['자막 위치', '맨 아래 →', '맨 위'],
    ['글꼴', '갈무리 11 →', '갈무리 14'],
    [translate('ko', 'audio.review.generic')],
  ]));
  expect(dialog.textContent).not.toMatch(/\/|[{}]|galmuri|highlight|[0-9]{64}/);
});
