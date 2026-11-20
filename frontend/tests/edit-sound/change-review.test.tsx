import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { createMockEditApi, sceneFieldOps, type ChangeOp, type EditApi } from '@/features/edit/api';
import { ChangeReview } from '@/features/edit/change-review';
import { EditProvider, useEdit } from '@/features/edit/edit-context';
import type { VideoView } from '@/features/edit/model';
import { ScenePanel } from '@/features/edit/scene-panel';
import { BGM_PATH, VOICE_PATH } from '@/features/edit/sound/model';
import { translate } from '@/shared/lib/i18n/catalog';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

import { soundView } from './support';

afterEach(cleanup);

const revision = '2'.repeat(64);

function Review({ showScene }: { showScene: boolean }) {
  const edit = useEdit();
  return <>{showScene ? <ScenePanel edit={edit} /> : null}<ChangeReview edit={edit} /></>;
}

async function renderPending(
  ops: ChangeOp[],
  {
    language = 'ko',
    view = soundView(),
    api = createMockEditApi(view),
    showScene = false,
  }: { language?: 'ko' | 'en'; view?: VideoView; api?: EditApi; showScene?: boolean } = {},
) {
  const plan = await api.change(view.video.id, {
    base_revision: view.video.revision,
    source: 'direct',
    target: { scene_id: null, pointer: null },
    ops,
  });
  vi.spyOn(api, 'load').mockResolvedValueOnce({ ...view, pending_change: plan.id });
  if (showScene) {
    // The mock applies direct visual changes immediately. Expose its saved result on confirmation.
    api.applyChange = async () => (await api.load(view.video.id)).video;
  }
  api.readChange = async () => ({
    ...plan, requires_confirmation: true, status: 'proposed', applied_revision: null,
    effects: showScene ? { ...plan.effects, scene_ids_render: [] } : plan.effects,
  });
  render(
    <LocaleProvider language={language} setLanguage={() => undefined}>
      <EditProvider active videoId={view.video.id} api={api}>
        <Review showScene={showScene} />
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

test('test_14_pending_scene_visual_changes_compare_the_values_from_the_scene_form', async () => {
  const view = soundView();
  const [firstId, secondId] = view.video.scene_order;
  const first = view.video.scenes[firstId];
  const second = view.video.scenes[secondId];
  const dialog = await renderPending([
    ...sceneFieldOps(first, { kind: 'background', value: 'bg_stars' }),
    ...sceneFieldOps(first, { kind: 'position', anchor: 'top_right' }),
    ...sceneFieldOps(second, { kind: 'expression', expressionId: 'expr_sad' }),
  ], { view });

  expectRows(dialog, [
    ['배경', '마을 →', '별빛'],
    ['위치', '가운데 아래 →', '오른쪽 위'],
    ['표정', '웃는 얼굴 →', '슬픈 얼굴'],
  ]);
  expect(dialog.textContent).not.toMatch(/background_id|expr_sad|top_right/);
});

test.each([
  { language: 'ko', expected: ['배경', '공원 →', '교실'] },
  { language: 'en', expected: ['Background', 'Park →', 'Classroom'] },
] as const)('test_14_default_pixel_backgrounds_are_named_in_$language', async ({ language, expected }) => {
  const view = soundView();
  const scene = view.video.scenes[view.video.scene_order[0]];
  if (scene.visual === null) throw new Error('The fixture must have scene visuals');
  scene.visual.background_id = 'bg_park';
  const dialog = await renderPending(sceneFieldOps(scene, { kind: 'background', value: 'bg_classroom' }), {
    view, language,
  });
  expectRows(dialog, [expected]);
});

test.each([
  { language: 'ko', name: '이름을 알 수 없는 항목', background: '배경', expression: '표정', apply: '바꾸기' },
  { language: 'en', name: 'Unnamed option', background: 'Background', expression: 'Face', apply: 'Change it' },
] as const)('test_14_the_scene_form_keeps_the_review_names_after_apply_in_$language', async ({
  language, name, background, expression, apply,
}) => {
  const view = soundView();
  const scene = view.video.scenes[view.video.scene_order[0]];
  if (scene.visual === null) throw new Error('The fixture must have scene visuals');
  const backgrounds = ['bg_synthetic_after', 'bg_synthetic_before'];
  const expressions = ['expr_synthetic_before', 'expr_synthetic_after'];
  scene.visual.background_id = backgrounds[1];
  scene.visual.characters[0].expression_id = expressions[0];
  const api = createMockEditApi(view);
  api.styleOptions = async () => ({ backgrounds, expressions, fonts: [] });
  const dialog = await renderPending([
    ...sceneFieldOps(scene, { kind: 'background', value: backgrounds[0] }),
    ...sceneFieldOps(scene, { kind: 'expression', expressionId: expressions[1] }),
  ], { view, language, api, showScene: true });

  await waitFor(() => expectRows(dialog, [
    [background, `${name} 2 →`, `${name} 1`],
    [expression, `${name} 1 →`, `${name} 2`],
  ]));
  fireEvent.click(within(dialog).getByRole('button', { name: apply }));
  await waitFor(() => {
    expect(within(screen.getByRole('combobox', { name: background })).getByText(`${name} 1`)).toBeTruthy();
    expect(within(screen.getByRole('combobox', { name: expression })).getByText(`${name} 2`)).toBeTruthy();
  });
});
