import { cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, test } from 'vitest';

import { ConceptApiError, createMockConceptApi, type MockConceptApi } from '@/features/concept/api';
import { PIXEL_REF } from '@/features/concept/model';
import {
  analyzeConceptReference,
  attachConceptExtras,
  applyConceptPlan,
  beginConcept,
  chooseCardTune,
  chooseConcept,
  confirmConcept,
  configureConceptApi,
  createConceptStyle,
  getConceptSnapshot,
  acknowledgeConceptChanged,
  loadConceptDeployment,
  reloadConcept,
  reloadConceptCatalog,
  resetConcept,
  resetConceptSessions,
  sendConcept,
  setConceptDraft,
  toggleConceptLock,
  undoConcept,
  useConcept,
} from '@/features/concept/store';
import type { Attachment, ConceptSnapshot, Settings } from '@/features/concept/types';

let api: MockConceptApi;

beforeEach(() => {
  resetConceptSessions();
  api = createMockConceptApi();
  configureConceptApi(api);
});

afterEach(cleanup);

function current(): ConceptSnapshot {
  const snapshot = getConceptSnapshot();
  if (snapshot === null) {
    throw new Error('No active concept session');
  }
  return snapshot;
}

/** The marked paths, without the per-change counts. */
function changedPathList(): string[] {
  return current().changedPaths.map((entry) => entry.path);
}

function text(id: string, content: string, name = `${id}.txt`): Attachment {
  return { id, kind: 'text', name, text: content, state: 'ready' };
}

function textFile(id: string, content: string, name = `${id}.md`): Attachment {
  return {
    id,
    kind: 'text',
    name,
    file: new File([content], name, { type: 'text/markdown' }),
    state: 'ready',
  };
}

function reference(id = 'ref-1'): Attachment {
  return {
    id,
    kind: 'reference',
    name: 'clip.mp4',
    file: new File(['video'], 'clip.mp4', { type: 'video/mp4' }),
    state: 'ready',
  };
}

function link(id = 'link-1'): Attachment {
  return {
    id,
    kind: 'link',
    name: 'example.invalid',
    url: 'https://youtu.be/00000000000',
    state: 'ready',
  };
}

function bgm(id = 'bgm-1'): Attachment {
  return {
    id,
    kind: 'bgm',
    name: 'bgm.wav',
    file: new File(['audio'], 'bgm.wav', { type: 'audio/wav' }),
    state: 'ready',
  };
}

function methodCount(method: string): number {
  return api.requests.filter((request) => request.method === method).length;
}

test('test_confirmed_concept_values_survive_route_remount_and_save_before_confirm', async () => {
  await beginConcept({ topic: '합성 주제', language: 'ko' });
  await reloadConceptCatalog();
  chooseConcept('/format/register', 'casual');
  setConceptDraft('대화 초안');

  const catalog = current().catalog;
  expect(catalog?.fonts).toHaveLength(2);
  for (const font of catalog?.fonts ?? []) {
    expect(font.revision).toMatch(/^[0-9a-f]{64}$/u);
  }

  await confirmConcept();
  expect(current().document.confirmed).toBe(true);
  expect(current().document.settings.format.register).toBe('casual');
  expect(current().draft).toBe('대화 초안');

  const saveIndex = api.requests.findIndex((request) => request.method === 'save');
  const confirmIndex = api.requests.findIndex((request) => request.method === 'confirm');
  expect(saveIndex).toBeGreaterThanOrEqual(0);
  expect(confirmIndex).toBeGreaterThan(saveIndex);
  const saved = api.requests[saveIndex].payload.settings as ConceptSnapshot['document']['settings'];
  expect(saved.format.layout).toEqual(current().document.settings.format.layout);
  expect(saved.visual.art_style).toEqual(current().document.settings.visual.art_style);
  expect(saved.format.story_structure).toBe(current().document.settings.format.story_structure);

  const firstMount = renderHook(() => useConcept());
  expect(firstMount.result.current?.document.confirmed).toBe(true);
  firstMount.unmount();
  const secondMount = renderHook(() => useConcept());
  expect(secondMount.result.current?.document.settings.format.register).toBe('casual');
  expect(secondMount.result.current?.document.confirmed).toBe(true);
  secondMount.unmount();
});

test('test_style_instruction_starts_a_job_and_applies_distinct_generated_assets', async () => {
  await beginConcept({ topic: '스타일', language: 'ko' });
  await reloadConceptCatalog();
  const before = current().document.settings.visual.character;
  const originalBody = before?.slots.body;

  await sendConcept('눈을 가늘게');
  expect(methodCount('submitStyle')).toBe(1);
  expect(methodCount('message')).toBe(0);
  expect(current().job?.state).toBe('succeeded');
  const pending = current().pending;
  expect(pending?.requires_confirmation).toBe(true);
  expect(pending?.confirmation_reasons).toContain('rebuild_render');
  expect(current().catalog?.styles.length).toBeGreaterThan(1);

  await applyConceptPlan();
  const applied = current();
  expect(applied.document.confirmed).toBe(false);
  expect(applied.pending).toBeNull();
  expect(applied.document.settings.visual.art_style.id).toMatch(/^style_gen_/u);
  const generatedBody = applied.document.settings.visual.character?.slots.body;
  expect(generatedBody).toMatch(/^gen\d+_body$/u);
  expect(generatedBody).not.toBe(originalBody);
  expect(methodCount('applyPlan')).toBe(1);

  undoConcept();
  expect(current().document.settings.visual.art_style.id).toBe('pixel');
  expect(current().document.settings.visual.character?.slots.body).toBe(originalBody);
});

test('test_text_materials_append_and_the_fifth_limit_blocks_submission', async () => {
  await beginConcept({ topic: '재료', attachments: [textFile('m1', '첫 번째 글')] });
  expect(current().document.attachments[0].text).toBe('첫 번째 글');

  await sendConcept('참고', [textFile('m2', '두 번째 글')]);
  const materials = current().document.attachments.filter((attachment) => attachment.kind === 'text');
  expect(materials.map((attachment) => attachment.text)).toEqual(['첫 번째 글', '두 번째 글']);

  await beginConcept({
    topic: '한도',
    attachments: [
      text('a1', '1'),
      text('a2', '2'),
      text('a3', '3'),
      text('a4', '4'),
      text('a5', '5'),
    ],
  });
  const messagesBefore = methodCount('message');
  await expect(sendConcept('', [text('a6', '6')])).rejects.toThrow('concept.error.materialLimit');
  expect(current().error).toBe('concept.error.materialLimit');
  expect(current().document.attachments).toHaveLength(5);
  expect(methodCount('message')).toBe(messagesBefore);
});

test('test_concept_deployment_is_read_through_the_injected_mock', async () => {
  expect(await loadConceptDeployment()).toBe('local');
  configureConceptApi(createMockConceptApi({ deployment: 'hosted' }));
  expect(await loadConceptDeployment()).toBe('hosted');
});

test('test_catalog_failure_is_reported_and_keeps_the_last_catalog', async () => {
  await beginConcept({ topic: '카탈로그' });
  await reloadConceptCatalog();
  const catalog = current().catalog;
  expect(catalog?.styles.length).toBeGreaterThan(0);

  api.failCatalog = true;
  await expect(reloadConceptCatalog()).rejects.toThrow('Catalog unavailable');
  expect(current().catalog).toEqual(catalog);
  expect(current().error).toBe('concept.error.catalog');
  expect(current().loading).toBe(false);
});

test('test_role_none_reset_restores_default_body_and_face_atomically', async () => {
  await beginConcept({ topic: '캐릭터' });
  await reloadConceptCatalog();
  const original = current().document.settings.visual.character;
  expect(original?.slots.body).not.toBeNull();
  expect(original?.slots.face).not.toBeNull();

  chooseConcept('/format/character_role', 'none');
  expect(current().document.settings.format.character_role).toBe('none');
  expect(current().document.settings.visual.character).toBeNull();

  resetConcept('/format/character_role');
  expect(current().error).toBeNull();
  expect(current().document.settings.format.character_role).toBe('presenter');
  expect(current().document.settings.visual.character?.slots.body).toBe(original?.slots.body);
  expect(current().document.settings.visual.character?.slots.face).toBe(original?.slots.face);
});

test('test_direct_and_chat_edits_share_one_state_and_block_invalid_combinations', async () => {
  await beginConcept({ topic: '조합' });
  await reloadConceptCatalog();

  chooseConcept('/caption/mode', 'typewriter');
  expect(current().error).toBe('concept.error.invalidCombination');
  expect(current().document.settings.caption.mode).toBe('sentence');

  chooseConcept('/format/layout', 'dialog_stage');
  chooseConcept('/caption/mode', 'typewriter');
  expect(current().document.settings.caption.mode).toBe('typewriter');
  chooseConcept('/format/layout', 'fixed_stage');
  expect(current().error).toBe('concept.error.invalidCombination');
  expect(current().document.settings.format.layout.id).toBe('dialog_stage');

  chooseConcept('/format/character_role', 'none');
  chooseConcept('/visual/character/slots/body', 'body_hero');
  expect(current().error).toBe('concept.error.invalidCombination');
  expect(current().document.settings.visual.character).toBeNull();

  await beginConcept({ topic: '대화' });
  await sendConcept('반말로 바꿔');
  expect(current().document.settings.format.register).toBe('casual');
  expect(current().document.settings.origins['/format/register']).toBe('user');
  chooseCardTune('its_like');
  expect(current().document.settings.format.register).toBe('friendly');
  expect(current().document.settings.format.story_structure).toBe('single_analogy');
  expect(current().document.settings.format.layout.id).toBe('full_stage');
  expect(current().cardTunes.just_three.register).toBe('casual');
  chooseCardTune('just_three');
  expect(current().document.settings.format.register).toBe('casual');

  await beginConcept({ topic: '막힌 대화' });
  await reloadConceptCatalog();
  await sendConcept('타자기 자막으로');
  expect(current().pending).toBeNull();
  expect(current().document.settings.caption.mode).toBe('sentence');
  expect(current().unsupported.length).toBeGreaterThan(0);
});

test('test_4_card_tunes_keep_each_card_values_and_replace_the_visible_ones', async () => {
  await beginConcept({ topic: '카드 값' });
  await reloadConceptCatalog();

  chooseConcept('/format/register', 'neutral');
  chooseCardTune('its_like');
  expect(current().document.settings.format.register).toBe('friendly');
  expect(current().document.settings.format.humor).toBe('light');
  expect(current().cardTunes.just_three.register).toBe('neutral');

  chooseConcept('/format/humor', 'none');
  expect(current().document.settings.origins['/format/humor']).toBe('user');
  chooseCardTune('what_if');
  expect(current().document.settings.format.humor).toBe('light');
  expect(current().document.settings.format.character_role).toBe('subject');
  expect(current().cardTunes.its_like.humor).toBe('none');

  chooseCardTune('its_like');
  expect(current().document.settings.format.humor).toBe('none');
  expect(current().document.settings.format.layout.id).toBe('full_stage');
});

test('test_a_late_chat_result_does_not_replace_a_concurrent_direct_edit', async () => {
  await beginConcept({ topic: '경쟁' });
  const sending = sendConcept('장면 중심으로');
  chooseConcept('/format/layout', 'dialog_stage');
  await sending;

  expect(current().document.settings.format.layout.id).toBe('dialog_stage');
  expect(current().document.settings.origins['/format/layout']).toBe('user');
});

test('test_jobs_finish_and_pending_plans_survive_a_screen_unmount', async () => {
  await beginConcept({ topic: '백그라운드' });
  const mounted = renderHook(() => useConcept());
  const style = createConceptStyle('더 따뜻한 색으로');
  mounted.unmount();
  await style;

  expect(current().job?.state).toBe('succeeded');
  expect(current().pending).not.toBeNull();
  expect(current().pending?.source).toBe('style');
});

test('test_a_new_session_does_not_receive_a_late_old_session_result', async () => {
  await beginConcept({ topic: '첫 영상' });
  const sending = sendConcept('반말로');
  await beginConcept({ topic: '둘째 영상' });
  await sending;

  expect(current().document.topic).toBe('둘째 영상');
  expect(current().document.settings.format.register).toBe('friendly');
});

test('test_apply_runs_once_for_a_proposed_plan_and_stale_bases_are_rejected', async () => {
  await beginConcept({ topic: '적용' });
  await sendConcept('장면 중심으로, 설명체로');
  const proposed = current().pending;
  expect(proposed?.status).toBe('proposed');
  expect(proposed?.requires_confirmation).toBe(true);
  expect(proposed?.ops.length).toBeGreaterThan(1);

  await expect(confirmConcept()).rejects.toThrow('concept.error.pendingPlan');
  expect(current().document.confirmed).toBe(false);
  expect(methodCount('confirm')).toBe(0);

  await applyConceptPlan();
  expect(current().document.confirmed).toBe(false);
  expect(current().pending).toBeNull();
  expect(current().document.settings.format.layout.id).toBe('full_stage');
  expect(current().document.settings.format.register).toBe('neutral');
  expect(methodCount('applyPlan')).toBe(1);
  await expect(applyConceptPlan()).rejects.toThrow('concept.error.planApplied');
  expect(methodCount('applyPlan')).toBe(1);

  await beginConcept({ topic: '오래된 계획' });
  await sendConcept('장면 중심으로, 설명체로');
  expect(current().pending).not.toBeNull();
  await api.save(current().document.id, current().document.settings);
  await expect(applyConceptPlan()).rejects.toMatchObject({ code: 'change_stale' });
  expect(current().error).toBe('concept.error.stale');
  expect(current().pending?.status).toBe('stale');
  expect(current().document.settings.format.layout.id).toBe('fixed_stage');
});

test('test_direct_and_single_chat_changes_keep_only_the_immediately_previous_state', async () => {
  await beginConcept({ topic: '되돌리기' });
  chooseConcept('/format/register', 'casual');
  expect(current().canUndo).toBe(true);
  undoConcept();
  expect(current().document.settings.format.register).toBe('friendly');
  expect(current().canUndo).toBe(false);

  await sendConcept('장면 중심으로');
  expect(current().document.settings.format.layout.id).toBe('full_stage');
  expect(current().canUndo).toBe(true);
  undoConcept();
  expect(current().document.settings.format.layout.id).toBe('fixed_stage');
  expect(current().canUndo).toBe(false);
});

test('test_reference_plan_preserves_user_values_until_confirmation', async () => {
  await beginConcept({ topic: '참고' });
  await reloadConceptCatalog();
  chooseConcept('/format/story_structure', 'hypothetical');
  await analyzeConceptReference(reference());

  expect(current().document.settings.format.story_structure).toBe('hypothetical');
  const pending = current().pending;
  expect(pending?.status).toBe('proposed');
  expect(pending?.requires_confirmation).toBe(true);
  expect(pending?.effects.overwrites_user_values).toContain('/format/story_structure');

  await applyConceptPlan();
  expect(current().document.confirmed).toBe(false);
  expect(current().document.settings.format.story_structure).toBe('single_analogy');
});

test('test_missing_style_assets_offer_an_explicit_replacement_plan', async () => {
  await beginConcept({ topic: '대체' });
  await reloadConceptCatalog();
  await createConceptStyle('새 그림체');
  await applyConceptPlan();
  const generated = current().document.settings.visual.art_style;
  expect(generated.id).toMatch(/^style_gen_/u);

  chooseConcept('/visual/art_style', PIXEL_REF);
  const pending = current().pending;
  expect(pending).not.toBeNull();
  expect(pending?.requires_confirmation).toBe(true);
  expect(pending?.ops.some((op) => op.op === 'set' && op.path === '/visual/character/slots/body')).toBe(true);
  expect(current().document.settings.visual.art_style.id).toBe(generated.id);
  expect(current().notes.length).toBeGreaterThan(0);

  await applyConceptPlan();
  expect(current().document.settings.visual.art_style.id).toBe('pixel');
  expect(current().document.settings.visual.character?.slots.body).toBe('body_hero');
  expect(current().document.settings.visual.character?.slots.face).toBe('face_neutral');
});

test('test_confirmation_locks_concept_fields_and_saves_full_selections', async () => {
  await beginConcept({ topic: '확정' });
  await reloadConceptCatalog();
  chooseConcept('/format/story_structure', 'single_analogy');
  toggleConceptLock('story_structure');
  await confirmConcept();

  const saved = api.requests.filter((request) => request.method === 'save').at(-1);
  const savedSettings = saved?.payload.settings as ConceptSnapshot['document']['settings'];
  expect(savedSettings.locks.story_structure).toBe('locked');
  expect(savedSettings.format.layout).toEqual(current().document.settings.format.layout);
  expect(savedSettings.visual.art_style).toEqual(current().document.settings.visual.art_style);

  chooseConcept('/format/story_structure', 'hypothetical');
  expect(current().error).toBe('concept.error.conceptLocked');
  expect(current().document.settings.format.story_structure).toBe('single_analogy');
  chooseCardTune('what_if');
  expect(current().error).toBe('concept.error.conceptLocked');
  resetConcept('/visual/art_style');
  expect(current().error).toBe('concept.error.conceptLocked');
  expect(current().document.confirmed).toBe(true);
});

test('test_chat_attachments_are_passed_through_and_bgm_uploads_to_the_project', async () => {
  await beginConcept({ topic: '첨부' });
  await expect(analyzeConceptReference(bgm())).rejects.toThrow(
    'concept.error.invalidCombination',
  );
  expect(methodCount('submitReference')).toBe(0);

  await sendConcept('참고해서 만들어 줘', [text('t1', '재료'), reference(), link(), bgm()]);
  const message = api.requests.filter(
    (request) => request.method === 'message' && request.kind === 'chat',
  ).at(-1);
  const attachments = message?.payload.attachments as { kind: string }[];
  expect(attachments.map((attachment) => attachment.kind).sort()).toEqual([
    'bgm',
    'link',
    'reference',
    'text',
  ]);
  const upload = api.requests.filter((request) => request.method === 'bgm_upload');
  expect(upload).toHaveLength(1);
  expect(upload[0].projectId).toBe(current().document.projectId);
  expect(upload[0].kind).toBe('bgm_upload');
  expect(methodCount('submitReference')).toBe(0);

  const material = current().document.attachments.find((attachment) => attachment.id === 't1');
  expect(material?.text).toBe('재료');
  expect(current().document.attachments.map((attachment) => attachment.id)).toEqual(
    expect.arrayContaining(['t1', 'ref-1', 'link-1', 'bgm-1']),
  );
});

test('test_notes_and_unsupported_are_visible_without_a_plan', async () => {
  await beginConcept({ topic: '안내' });
  await sendConcept('실제 사람 사진으로 춤추는 영상을 만들어 줘');

  expect(current().pending).toBeNull();
  expect(current().notes).toContain('이 요청에서 바꿀 컨셉 값을 찾지 못했어요.');
  expect(current().unsupported).toContain('실제 사람 사진으로 춤추는 영상을 만들어 줘: 이 요청은 컨셉 값으로 바꿀 수 없어요.');
});

test('test_explicit_chat_values_take_priority_over_attached_reference_suggestions', async () => {
  await beginConcept({ topic: '혼합 요청' });
  await sendConcept('만약 별이 사라진다면', [reference()]);
  const pending = current().pending;
  expect(pending?.ops).toContainEqual(expect.objectContaining({
    op: 'set', path: '/format/story_structure', value: 'hypothetical', origin: 'user',
  }));
  await applyConceptPlan();
  expect(current().document.settings.format.story_structure).toBe('hypothetical');
  expect(current().document.settings.origins['/format/story_structure']).toBe('user');
  expect(changedPathList()).toContain('/format/story_structure');
});

test('test_failed_reread_after_draft_keeps_materials_shows_error_and_still_starts_held_back_files', async () => {
  await beginConcept({ topic: '재료', attachments: [text('t1', '남는 글')] });
  const videoId = current().document.id;
  api.load = () => Promise.reject(new ConceptApiError('internal', 500, 'Read failed'));

  await reloadConcept(videoId);
  expect(current().readError).toBe('concept.error.jobFailed');
  expect(current().readState).toBe('failed');
  expect(current().document.attachments.map((attachment) => attachment.id)).toContain('t1');

  await attachConceptExtras([reference()]);
  expect(api.requests.some((request) => request.method === 'message' && request.kind === 'reference')).toBe(true);
  // An attachment job may clear the general error, never the failed read.
  expect(current().readError).toBe('concept.error.jobFailed');
});

test('test_5_the_draft_reload_freezes_the_first_reply_and_marks_filled_values', async () => {
  await beginConcept({ topic: '초안', language: 'ko', duration: 30 });
  const videoId = current().document.id;
  expect(current().opening.format.story_structure).toBe('numbered_three');
  expect(current().changedPaths).toEqual([]);

  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.format.story_structure = 'hypothetical';
  stored.settings.format.card_id = 'what_if';
  stored.settings.origins['/format/story_structure'] = 'llm';
  stored.settings.origins['/format/card_id'] = 'llm';
  await reloadConcept(videoId);

  expect(current().opening.format.story_structure).toBe('hypothetical');
  expect(changedPathList()).toContain('/format/story_structure');
  expect(changedPathList()).not.toContain('/visual/art_style');

  // One user pick clears the draft's mark for that value and adds none.
  chooseConcept('/format/story_structure', 'numbered_three');
  expect(changedPathList()).not.toContain('/format/story_structure');
  expect(changedPathList()).toContain('/format/card_id');

  chooseConcept('/format/register', 'casual');
  stored.settings.format.story_structure = 'numbered_three';
  stored.settings.origins['/format/story_structure'] = 'llm';
  await reloadConcept(videoId);
  expect(current().opening.format.story_structure).toBe('hypothetical');
});

test('test_5_a_chat_change_marks_the_value_until_the_screen_acknowledges_it', async () => {
  await beginConcept({ topic: '대화', language: 'ko' });
  await sendConcept('만약 별이 사라진다면');

  expect(changedPathList()).toContain('/format/story_structure');
  acknowledgeConceptChanged();
  expect(current().changedPaths).toEqual([]);
});

test('test_5_the_draft_reload_marks_a_value_quoted_from_the_sentence', async () => {
  await beginConcept({ topic: '2분', language: 'ko', duration: 30 });
  const videoId = current().document.id;
  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.target_duration_s = 120;
  stored.settings.origins['/target_duration_s'] = 'user';

  await reloadConcept(videoId);

  expect(current().document.settings.target_duration_s).toBe(120);
  expect(current().readState).toBe('ready');
  // The server calls a value quoted from the sentence `user`; the highlight
  // follows the actual change, not the origin label.
  expect(changedPathList()).toContain('/target_duration_s');
});

test('test_5_the_draft_reload_keeps_directly_picked_values_valid', async () => {
  await beginConcept({ topic: '구성', language: 'ko', duration: 30 });
  await reloadConceptCatalog();
  const videoId = current().document.id;
  chooseConcept('/format/layout', 'full_stage');
  expect(current().document.settings.format.layout.id).toBe('full_stage');

  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.format.layout = { ...stored.settings.format.layout, id: 'dialog_stage' };
  stored.settings.caption.mode = 'typewriter';
  stored.settings.origins['/caption/mode'] = 'llm';

  await reloadConcept(videoId);

  // The direct pick and the caption that constrains it stay together, so the
  // merged pair never becomes the invalid full-stage typewriter.
  expect(current().document.settings.format.layout.id).toBe('full_stage');
  expect(current().document.settings.caption.mode).toBe('sentence');
  expect(current().readState).toBe('ready');
  await confirmConcept();
  expect(current().document.confirmed).toBe(true);
});

test('test_5_an_unapplied_draft_does_not_become_the_first_reply', async () => {
  await beginConcept({ topic: '제안', language: 'ko', duration: 30 });
  const videoId = current().document.id;
  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.target_duration_s = 120;

  await reloadConcept(videoId, false);

  expect(current().document.settings.target_duration_s).toBe(120);
  expect(current().readState).toBe('failed');
  expect(current().opening.target_duration_s).toBe(30);
});

test('test_5_a_new_video_starts_with_no_concept_read', async () => {
  await beginConcept({ topic: '첫 영상', language: 'ko' });
  const firstId = current().document.id;
  await reloadConcept(firstId);
  expect(current().readState).toBe('ready');

  await beginConcept({ topic: '둘째 영상', language: 'ko' });

  expect(current().document.id).not.toBe(firstId);
  expect(current().readState).toBe('idle');
});

test('test_5_undo_forgets_the_paths_it_restored', async () => {
  await beginConcept({ topic: '대화', language: 'ko' });
  await sendConcept('2분으로 해 줘');
  if (current().pending !== null) await applyConceptPlan();
  expect(changedPathList()).toContain('/target_duration_s');
  const before = current().forgotten?.version ?? 0;

  undoConcept();

  expect(changedPathList()).not.toContain('/target_duration_s');
  expect(current().forgotten?.version).toBeGreaterThan(before);
  expect(current().forgotten?.paths).toContain('/target_duration_s');
});

test('test_5_a_direct_style_pick_does_not_hide_the_draft_role', async () => {
  await beginConcept({ topic: '그림체', language: 'ko' });
  await reloadConceptCatalog();
  const videoId = current().document.id;
  const flat = api.catalogValue().styles[1]?.ref;
  if (flat === undefined) throw new Error('The mock catalog has no second style');
  chooseConcept('/visual/art_style', flat);
  if (current().pending !== null) await applyConceptPlan();
  expect(current().document.settings.visual.art_style.id).toBe(flat.id);

  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.format.character_role = 'subject';
  stored.settings.origins['/format/character_role'] = 'llm';

  await reloadConcept(videoId);

  // The style pick changed only the style; the draft's role still applies.
  expect(current().document.settings.visual.art_style.id).toBe(flat.id);
  expect(current().document.settings.format.character_role).toBe('subject');
  expect(current().readState).toBe('ready');
});

test('test_5_a_direct_duration_keeps_its_calculated_scene_count', async () => {
  await beginConcept({ topic: '길이', language: 'ko', duration: 30 });
  const videoId = current().document.id;
  chooseConcept('/target_duration_s', 120);
  expect(current().document.settings.target_duration_s).toBe(120);
  expect(current().document.settings.format.scene_count).toBe(11);

  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.target_duration_s = 30;
  stored.settings.format.scene_count = 5;
  stored.settings.origins['/target_duration_s'] = 'llm';
  stored.settings.origins['/format/scene_count'] = 'llm';

  await reloadConcept(videoId);

  // Both values the direct pick actually wrote survive the draft's 30-second values.
  expect(current().document.settings.target_duration_s).toBe(120);
  expect(current().document.settings.format.scene_count).toBe(11);
  expect(current().readState).toBe('ready');
});

test('test_5_a_character_slot_change_marks_only_that_slot', async () => {
  await beginConcept({ topic: '모자', language: 'ko' });
  await reloadConceptCatalog();
  const videoId = current().document.id;
  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  const character = stored.settings.visual.character;
  if (character === null) throw new Error('The mock session has no character');
  const catalog = current().catalog;
  if (catalog === null) throw new Error('The mock catalog is missing');
  const style = catalog.styles.find(
    (entry) => entry.ref.id === stored.settings.visual.art_style.id,
  );
  if (style === undefined) throw new Error('The mock style is missing');
  const template = style.manifest.assets.find((entry) => entry.kind === 'part');
  if (template === undefined) throw new Error('The mock style has no part asset');
  // The fixture has one asset per body and face; add a distinct usable hat so
  // the catalog can validate a slot-only change.
  style.manifest.assets.push({ ...template, id: 'hat_test', slot: 'hat' });
  style.manifest.rig.slots.hat.push('hat_test');
  character.slots.hat = 'hat_test';
  stored.settings.origins['/visual/character/slots/hat'] = 'llm';

  await reloadConcept(videoId);

  const marked = changedPathList();
  expect(marked).toContain('/visual/character/slots/hat');
  for (const name of ['body', 'face', 'hair', 'outfit', 'prop']) {
    expect(marked).not.toContain(`/visual/character/slots/${name}`);
  }
  expect(marked).not.toContain('/visual/character');
});

test('test_5_a_successful_reread_clears_the_read_error', async () => {
  await beginConcept({ topic: '재읽기', language: 'ko' });
  const videoId = current().document.id;
  const load = api.load.bind(api);
  api.load = () => Promise.reject(new ConceptApiError('internal', 500, 'Read failed'));
  await reloadConcept(videoId);
  expect(current().readError).toBe('concept.error.jobFailed');

  api.load = load;
  await reloadConcept(videoId);

  expect(current().readError).toBeNull();
  expect(current().readState).toBe('ready');
});
test('test_5_an_unapplied_draft_retry_does_not_write_the_success_reply', async () => {
  await beginConcept({ topic: '제안', language: 'ko', duration: 30 });
  const videoId = current().document.id;
  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.target_duration_s = 120;
  const load = api.load.bind(api);
  api.load = () => Promise.reject(new ConceptApiError('internal', 500, 'Read failed'));
  await reloadConcept(videoId, false);
  expect(current().readError).toBe('concept.error.jobFailed');

  api.load = load;
  await reloadConcept(videoId);

  // The document read succeeded, but the draft still did not apply.
  expect(current().readError).toBeNull();
  expect(current().readState).toBe('failed');
  expect(current().opening.target_duration_s).toBe(30);
  expect(current().document.settings.target_duration_s).toBe(120);
});

test('test_5_a_layout_conflict_does_not_restore_the_draft_role', async () => {
  await beginConcept({ topic: '역할', language: 'ko' });
  await reloadConceptCatalog();
  const videoId = current().document.id;
  const catalog = current().catalog;
  if (catalog === null) throw new Error('The mock catalog is missing');
  const style = catalog.styles.find((entry) => entry.ref.id === current().document.settings.visual.art_style.id);
  if (style === undefined) throw new Error('The mock style is missing');
  const template = style.manifest.assets.find((entry) => entry.kind === 'part');
  if (template === undefined) throw new Error('The mock style has no part asset');
  style.manifest.assets.push({ ...template, id: 'hat_test', slot: 'hat' });
  style.manifest.rig.slots.hat.push('hat_test');
  chooseConcept('/format/layout', 'full_stage');
  chooseConcept('/visual/character/slots/hat', 'hat_test');
  expect(current().document.settings.visual.character?.slots.hat).toBe('hat_test');

  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.format.layout = { ...stored.settings.format.layout, id: 'dialog_stage' };
  stored.settings.caption.mode = 'typewriter';
  stored.settings.format.character_role = 'subject';
  stored.settings.origins['/format/layout'] = 'llm';
  stored.settings.origins['/caption/mode'] = 'llm';
  stored.settings.origins['/format/character_role'] = 'llm';

  await reloadConcept(videoId);

  // Only the failing layout/caption pair is restored; the draft's role stays.
  expect(current().document.settings.format.layout.id).toBe('full_stage');
  expect(current().document.settings.caption.mode).toBe('sentence');
  expect(current().document.settings.format.character_role).toBe('subject');
  expect(current().readState).toBe('ready');
});

test('test_5_a_created_character_marks_its_body_slot', async () => {
  const create = api.create.bind(api);
  let draftCharacter: Settings['visual']['character'] = null;
  api.create = async (input) => {
    const document = await create(input);
    draftCharacter = document.settings.visual.character;
    document.settings.format.character_role = 'none';
    document.settings.visual.character = null;
    return document;
  };
  await beginConcept({ topic: '캐릭터', language: 'ko' });
  const videoId = current().document.id;
  expect(current().document.settings.visual.character).toBeNull();
  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.format.character_role = 'subject';
  stored.settings.visual.character = draftCharacter;

  await reloadConcept(videoId);

  const marked = changedPathList();
  expect(marked).toContain('/visual/character/slots/body');
  expect(marked).not.toContain('/visual/character');
  expect(current().readState).toBe('ready');
});

test('test_5_a_unfit_hat_pick_keeps_the_draft_role_and_length', async () => {
  await beginConcept({ topic: '모자', language: 'ko' });
  await reloadConceptCatalog();
  const videoId = current().document.id;
  const catalog = current().catalog;
  if (catalog === null) throw new Error('The mock catalog is missing');
  const own = catalog.styles[0];
  const other = catalog.styles[1];
  if (own === undefined || other === undefined) throw new Error('The mock catalog needs two styles');
  const template = own.manifest.assets.find((entry) => entry.kind === 'part');
  if (template === undefined) throw new Error('The mock style has no part asset');
  // A hat that only the current style offers.
  own.manifest.assets.push({ ...template, id: 'hat_only_here', slot: 'hat' });
  own.manifest.rig.slots.hat.push('hat_only_here');
  chooseConcept('/visual/character/slots/hat', 'hat_only_here');
  if (current().pending !== null) await applyConceptPlan();
  expect(current().document.settings.visual.character?.slots.hat).toBe('hat_only_here');

  const stored = api.sessions.get(videoId);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.visual.art_style = other.ref;
  stored.settings.visual.theme_id = other.manifest.themes[0]?.id ?? stored.settings.visual.theme_id;
  stored.settings.format.character_role = 'subject';
  stored.settings.target_duration_s = 120;
  stored.settings.origins['/format/character_role'] = 'llm';
  stored.settings.origins['/target_duration_s'] = 'llm';

  await reloadConcept(videoId);

  const settings = current().document.settings;
  expect(settings.visual.art_style.id).toBe(other.ref.id);
  expect(settings.visual.character?.slots.hat).not.toBe('hat_only_here');
  expect(settings.format.character_role).toBe('subject');
  expect(settings.target_duration_s).toBe(120);
  expect(current().readNotice).toBe('concept.reason.user_value_overwrite');
});
