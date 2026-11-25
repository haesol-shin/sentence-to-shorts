import { beforeEach, describe, expect, test } from 'vitest';

import { MockScriptApi, ScriptApiError } from '@/features/script/api';
import {
  applyRewrite,
  applyTone,
  applyToneScene,
  clearTarget,
  configureScriptApi,
  confirmScript,
  dismissRewrite,
  dismissTone,
  dismissToneScene,
  editLine,
  ensureScript,
  focusScene,
  getScriptSnapshot,
  moveScene,
  rewriteScene,
  setLength,
  setRegister,
  setSceneCount,
  stopRewrite,
  undo,
} from '@/features/script/store';
import { recommendedSceneCount } from '@/features/concept/model';
import {
  configureScriptSceneCounts,
  DURATIONS,
  totalSeconds,
} from '@/features/script/model';
import type { ScriptDocument, ScriptSnapshot } from '@/features/script/types';
import type { VideoView } from '@/shared/api/client';
import { mockResponse } from '@/shared/api/mock';
import {
  confirmedMockScripts,
  withMockScript,
  withMockStory,
  withMockStoryStills,
} from '@/shared/api/mock/story';

let api: MockScriptApi;

const COFFEE = '커피를 고르는 세 가지 기준';
const FIRST_LINE = `「${COFFEE}」 이야기를 확인해요.`;
const CASUAL_FIRST_LINE = `「${COFFEE}」 이야기를 확인해.`;

function snapshot(): ScriptSnapshot {
  const current = getScriptSnapshot();
  if (current === null) {
    throw new Error('The script session did not open');
  }
  return current;
}

function firstSceneId(): string {
  const id = snapshot().document.scene_order[0];
  if (id === undefined) {
    throw new Error('The script has no scene');
  }
  return id;
}

async function open(delayMs = 0): Promise<void> {
  api = new MockScriptApi({ rewriteDelayMs: delayMs });
  configureScriptApi(api);
  await ensureScript('ko');
}

beforeEach(async () => {
  configureScriptSceneCounts(DURATIONS.map((seconds) => recommendedSceneCount(seconds)));
  await open();
});

describe('script state', () => {
  test('test_2_no_preview_or_confirm_request_before_the_script_gate', async () => {
    const id = firstSceneId();
    const line = snapshot().document.scenes[id]?.lines[0];
    expect(line).toBeDefined();
    editLine(id, line!.id, '고친 대사예요.');

    expect(api.count('confirm')).toBe(0);
    expect(api.count('previews')).toBe(0);
    await expect(api.requestPreviews(snapshot().document)).rejects.toBeInstanceOf(ScriptApiError);
    expect(api.count('previews')).toBe(0);

    await confirmScript();

    expect(snapshot().confirmed).toBe(true);
    await api.requestPreviews(snapshot().document);
    expect(api.count('previews')).toBe(1);
  });

  test('test_2_one_text_box_saves_display_and_speech_together', () => {
    const id = firstSceneId();
    const line = snapshot().document.scenes[id]?.lines[0];
    expect(line).toBeDefined();

    editLine(id, line!.id, '같은 글이 화면과 말에 함께 쓰여요.');

    const saved = snapshot().document.scenes[id]?.lines[0];
    expect(saved?.display_text).toBe('같은 글이 화면과 말에 함께 쓰여요.');
    expect(saved?.speech_text).toBe('같은 글이 화면과 말에 함께 쓰여요.');
  });

  test('test_2_a_user_line_keeps_its_own_breaks', () => {
    const id = firstSceneId();
    const line = snapshot().document.scenes[id]?.lines[0];
    const text = '따옴표 "이" 앞에서\n줄을 바꿔요.';

    editLine(id, line!.id, text);

    const saved = snapshot().document.scenes[id]?.lines[0];
    expect(saved?.display_text).toBe(text);
    expect(saved?.speech_text).toBe(text);
    expect((saved?.display_text.match(/\n/gu) ?? []).length).toBe(1);
  });

  test('test_2_a_new_video_opens_its_own_script', async () => {
    await ensureScript('ko', {
      id: 'v_00000000000000000000000001',
      topic: '첫 번째 주제',
      script: '첫 번째 주제',
    });
    const first = snapshot().document;
    expect(first.topic).toBe('첫 번째 주제');
    editLine(first.scene_order[0]!, first.scenes[first.scene_order[0]!]!.lines[0]!.id, '첫 영상의 대사예요.');

    await ensureScript('ko', {
      id: 'v_00000000000000000000000002',
      topic: '두 번째 주제',
      script: '두 번째 주제',
    });
    const second = snapshot().document;

    expect(second.id).toBe('v_00000000000000000000000002');
    expect(second.topic).toBe('두 번째 주제');
    expect(second.scenes[second.scene_order[0]!]?.lines[0]?.display_text).toBe('두 번째 주제');
    expect(second.scenes[second.scene_order[0]!]?.lines[0]?.display_text).not.toBe(
      '첫 영상의 대사예요.',
    );
    expect(snapshot().confirmed).toBe(false);
  });

  test('test_2_the_user_script_opens_unchanged', async () => {
    const script = '사용자 대본 첫 줄\n둘째 줄';
    await ensureScript('ko', { id: 'v_user_script', topic: '사용자 주제', script });
    const document = snapshot().document;
    const first = document.scenes[document.scene_order[0]!];

    expect(document.script.raw_text).toBe(script);
    expect(document.script.source).toBe('user');
    expect(first?.lines.map((line) => line.display_text)).toEqual([
      '사용자 대본 첫 줄',
      '둘째 줄',
    ]);
    expect(first?.lines[0]?.speech_text).toBe('사용자 대본 첫 줄');
  });

  test('test_1_the_same_sentence_in_a_new_video_opens_a_fresh_session', async () => {
    await ensureScript('ko', { id: 'session-1', topic: COFFEE, script: COFFEE });
    const firstId = firstSceneId();
    const firstLineId = snapshot().document.scenes[firstId]?.lines[0]?.id;
    editLine(firstId, firstLineId!, '첫 영상의 대사예요.');
    await confirmScript();

    await ensureScript('ko', { id: 'session-2', topic: COFFEE, script: COFFEE });
    const second = snapshot().document;

    expect(second.id).toBe('session-2');
    expect(second.scenes[second.scene_order[0]!]?.lines[0]?.display_text).toBe(COFFEE);
    expect(snapshot().confirmed).toBe(false);
  });

  test('test_3_the_interface_language_does_not_reset_the_video_script', async () => {
    await ensureScript('ko', { id: 'v_language', topic: COFFEE, script: COFFEE });
    const id = firstSceneId();
    const lineId = snapshot().document.scenes[id]?.lines[0]?.id;
    editLine(id, lineId!, '언어를 바꿔도 남아요.');

    await ensureScript('en', { id: 'v_language', topic: COFFEE, script: COFFEE });

    expect(snapshot().document.id).toBe('v_language');
    expect(snapshot().document.language).toBe('ko');
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe('언어를 바꿔도 남아요.');
  });

  test('test_10a_length_applies_the_concept_scene_count', () => {
    const id = firstSceneId();
    const firstText = snapshot().document.scenes[id]?.lines[0]?.display_text;

    setLength(120);

    expect(snapshot().document.target_duration_s).toBe(120);
    expect(snapshot().document.scene_order).toHaveLength(11);
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe(firstText);
    expect(snapshot().document.scenes[snapshot().document.scene_order[10]!]?.lines[0]?.display_text).toBe(
      '',
    );
  });

  test('test_12_the_scene_buttons_move_the_order', () => {
    const [first, second] = snapshot().document.scene_order;
    expect(first).toBeDefined();
    expect(second).toBeDefined();

    moveScene(first!, 1);

    expect(snapshot().document.scene_order.slice(0, 2)).toEqual([second, first]);
  });

  test('test_12_reordering_then_changing_the_count_never_repeats_a_scene', () => {
    setSceneCount(8);
    const moved = snapshot().document.scene_order[5];
    expect(moved).toBeDefined();
    moveScene(moved!, -1);
    setSceneCount(5);
    setSceneCount(8);

    const order = snapshot().document.scene_order;
    expect(order).toHaveLength(8);
    expect(new Set(order).size).toBe(8);
    expect(order.every((id) => snapshot().document.scenes[id] !== undefined)).toBe(true);
  });

  test('test_2_a_repeated_scene_order_is_rejected_at_confirm', async () => {
    const document = snapshot().document;
    const first = document.scene_order[0];
    const broken: ScriptDocument = {
      ...document,
      scene_order: [first!, first!, ...document.scene_order.slice(2)],
    };
    await expect(api.confirm(broken)).rejects.toMatchObject({ code: 'duplicate_order' });
  });

  test('test_2_appended_scenes_start_empty_and_block_confirm', () => {
    setSceneCount(8);
    const appended = snapshot().document.scene_order[7];
    expect(appended).toBeDefined();
    expect(snapshot().document.scenes[appended!]?.lines[0]?.display_text).toBe('');
    expect(snapshot().nextBlockedReason).toBe('script.reason.empty');
    expect(snapshot().confirmed).toBe(false);
  });

  test('test_2_a_line_over_the_contract_limit_blocks_confirm', async () => {
    const id = firstSceneId();
    const line = snapshot().document.scenes[id]?.lines[0];
    expect(line).toBeDefined();

    editLine(id, line!.id, '가'.repeat(301));
    expect(snapshot().nextBlockedReason).toBe('script.reason.lineTooLong');
    await expect(api.confirm(snapshot().document)).rejects.toMatchObject({ code: 'script_invalid' });

    editLine(id, line!.id, '가'.repeat(300));
    expect(snapshot().nextBlockedReason).toBeNull();
    await confirmScript();
    expect(snapshot().confirmed).toBe(true);
  });

  test('test_2_stopping_a_rewrite_keeps_the_original_lines', async () => {
    await open(50);
    const id = firstSceneId();
    const original = snapshot().document.scenes[id]?.lines.map((line) => line.display_text);

    const running = rewriteScene(id);
    stopRewrite();
    await running;

    expect(snapshot().workingSceneId).toBeNull();
    expect(snapshot().rewrite).toBeNull();
    expect(snapshot().document.scenes[id]?.lines.map((line) => line.display_text)).toEqual(original);
    expect(api.count('cancel')).toBe(1);
    expect(snapshot().error).toBe('script.stopped');
  });

  test('test_8a_an_applied_rewrite_can_be_undone_once', async () => {
    const id = firstSceneId();
    const original = snapshot().document.scenes[id]?.lines[0]?.display_text ?? '';

    await rewriteScene(id);
    expect(snapshot().rewrite?.sceneId).toBe(id);
    expect(snapshot().rewrite?.after[0]?.startsWith('다시 말하면, ')).toBe(true);

    applyRewrite();
    expect(snapshot().changedSceneIds).toContain(id);
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).not.toBe(original);
    expect(snapshot().canUndo).toBe(true);

    undo();
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe(original);
    expect(snapshot().canUndo).toBe(false);
  });

  test('test_8a_typing_in_a_line_and_a_move_are_each_undone_as_one_step', () => {
    const id = firstSceneId();
    const line = snapshot().document.scenes[id]?.lines[0];
    expect(snapshot().canUndo).toBe(false);

    editLine(id, line!.id, '원');
    editLine(id, line!.id, '원두 향을 먼저 맡아 봐요');
    expect(snapshot().canUndo).toBe(true);
    undo();
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe(FIRST_LINE);
    expect(snapshot().canUndo).toBe(false);

    const order = [...snapshot().document.scene_order];
    moveScene(order[2]!, -1);
    expect(snapshot().document.scene_order).not.toEqual(order);
    undo();
    expect(snapshot().document.scene_order).toEqual(order);
  });

  test('test_2_the_mock_edit_opens_on_the_confirmed_order_and_lines', async () => {
    const id = firstSceneId();
    const line = snapshot().document.scenes[id]?.lines[0];
    editLine(id, line!.id, '원두 향을 먼저 맡아 봐요');
    const third = snapshot().document.scene_order[2]!;
    moveScene(third, -1);
    await confirmScript();

    const script = confirmedMockScripts.get(snapshot().document.id);
    expect(script?.map((scene) => scene.story)).toEqual([0, 2, 1, 3, 4]);
    expect(script?.[0]?.lines[0]).toBe('원두 향을 먼저 맡아 봐요');

    // The recorded getVideo answer the mock video read starts from.
    const template = mockResponse({ method: 'GET', path: '/videos/v_1' }).body as VideoView;
    const story = withMockStory(template.video);
    const { video, build } = withMockScript(story, withMockStoryStills(template.build, template.video), script!);
    expect(video.scene_order).toEqual([0, 2, 1, 3, 4].map((index) => story.scene_order[index]));
    expect(video.scenes[video.scene_order[0]!]?.lines.map((entry) => entry.display_text)).toEqual(
      script![0]!.lines,
    );
    expect(Object.keys(build.scenes).sort()).toEqual([...video.scene_order].sort());
  });

  test('test_8a_stopping_a_later_rewrite_keeps_the_earlier_undo', async () => {
    const first = firstSceneId();
    await rewriteScene(first);
    applyRewrite();
    const applied = snapshot().document.scenes[first]?.lines[0]?.display_text ?? '';
    const second = snapshot().document.scene_order[1];
    expect(second).toBeDefined();

    const running = rewriteScene(second!);
    stopRewrite();
    await running;

    expect(snapshot().canUndo).toBe(true);
    undo();
    expect(snapshot().document.scenes[first]?.lines[0]?.display_text).not.toBe(applied);
    expect(snapshot().document.scenes[first]?.lines[0]?.display_text).toBe(FIRST_LINE);
  });

  test('test_2_each_jump_request_moves_to_the_scene_again', () => {
    const id = firstSceneId();
    focusScene(id);
    const first = snapshot().focusToken;
    focusScene(id);

    expect(snapshot().highlightedSceneId).toBe(id);
    expect(snapshot().focusToken).toBe(first + 1);
  });

  test('test_26_the_tone_preview_shows_the_old_and_new_line_in_every_scene', () => {
    setRegister('neutral');

    const tone = snapshot().tone;
    expect(tone).not.toBeNull();
    expect(tone?.to).toBe('neutral');
    expect(tone?.scenes).toHaveLength(5);
    expect(snapshot().document.register).toBe('friendly');
    for (const scene of tone?.scenes ?? []) {
      expect(scene.lines.length).toBeGreaterThan(0);
      for (const line of scene.lines) {
        expect(line.after).not.toBe(line.before);
      }
    }
    expect(snapshot().document.scenes[firstSceneId()]?.lines[0]?.display_text).toBe(FIRST_LINE);
  });

  test('test_26_one_scene_takes_the_tone_and_the_other_scenes_stay_asked', () => {
    setRegister('casual');
    const id = firstSceneId();

    applyToneScene(id);

    expect(snapshot().tone?.scenes.map((scene) => scene.sceneId)).not.toContain(id);
    expect(snapshot().tone?.scenes).toHaveLength(4);
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe(CASUAL_FIRST_LINE);
    expect(snapshot().changedSceneIds).toEqual([id]);
    expect(snapshot().document.register).toBe('casual');

    // The rest of the proposal still waits for its own decision.
    expect(snapshot().tone?.scenes).toHaveLength(4);
    applyTone();
    expect(snapshot().tone).toBeNull();
    expect(snapshot().changedSceneIds).toHaveLength(5);
  });

  test('test_26_one_scene_keeps_its_tone_and_the_others_stay_asked', () => {
    setRegister('casual');
    const id = firstSceneId();

    dismissToneScene(id);
    expect(snapshot().tone?.scenes.map((scene) => scene.sceneId)).not.toContain(id);
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe(FIRST_LINE);

    for (const scene of snapshot().tone?.scenes ?? []) {
      dismissToneScene(scene.sceneId);
    }
    expect(snapshot().tone).toBeNull();
    expect(snapshot().document.register).toBe('friendly');
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe(FIRST_LINE);
  });

  test('test_26_applying_the_tone_marks_scenes_and_recounts_the_length', () => {
    const before = totalSeconds(snapshot().document);
    setRegister('casual');
    expect(totalSeconds(snapshot().document)).toBe(before);

    applyTone();

    expect(snapshot().tone).toBeNull();
    expect(snapshot().changedSceneIds).toHaveLength(5);
    expect(totalSeconds(snapshot().document)).toBeLessThan(before);
    expect(snapshot().document.scenes[firstSceneId()]?.lines[0]?.display_text).toBe(
      CASUAL_FIRST_LINE,
    );
    expect(snapshot().document.register).toBe('casual');
  });

  test('test_26_keeping_the_old_tone_restores_the_text_without_touching_the_register', () => {
    setRegister('neutral');
    dismissTone();

    expect(snapshot().tone).toBeNull();
    expect(snapshot().document.register).toBe('friendly');
    expect(snapshot().document.scenes[firstSceneId()]?.lines[0]?.display_text).toBe(FIRST_LINE);
  });

  test('test_26_undo_after_a_tone_change_restores_the_field_and_the_text', () => {
    setRegister('neutral');
    applyTone();

    expect(snapshot().canUndo).toBe(true);
    undo();

    expect(snapshot().document.register).toBe('friendly');
    expect(snapshot().changedSceneIds).toHaveLength(0);
    expect(snapshot().document.scenes[firstSceneId()]?.lines[0]?.display_text).toBe(FIRST_LINE);
  });

  test('test_2_the_step_action_waits_for_a_pending_tone_or_rewrite', async () => {
    setRegister('neutral');
    expect(snapshot().nextBlockedReason).toBe('script.reason.tone');
    dismissTone();
    expect(snapshot().nextBlockedReason).toBeNull();

    const id = firstSceneId();
    const target = snapshot().document.scenes[id]?.lines[0];
    await rewriteScene(id);
    expect(snapshot().nextBlockedReason).toBe('script.reason.rewrite');
    dismissRewrite();
    expect(snapshot().nextBlockedReason).toBeNull();

    await confirmScript();
    expect(snapshot().confirmed).toBe(true);
    expect(snapshot().nextBlockedReason).toBeNull();

    const before = snapshot().document.scenes[id]?.lines[0]?.display_text;
    editLine(id, target!.id, '확인한 뒤에도 고칠 수 있어요.');
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe('확인한 뒤에도 고칠 수 있어요.');
    expect(before).not.toBe('확인한 뒤에도 고칠 수 있어요.');
  });

  test('test_5_the_undo_is_locked_while_a_rewrite_review_is_open', async () => {
    setRegister('neutral');
    applyTone();
    const id = firstSceneId();
    await rewriteScene(id);

    expect(snapshot().canUndo).toBe(false);
    undo();
    expect(snapshot().rewrite).not.toBeNull();
    expect(snapshot().document.register).toBe('neutral');

    dismissRewrite();
    expect(snapshot().canUndo).toBe(true);
    undo();
    expect(snapshot().document.register).toBe('friendly');
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe(FIRST_LINE);
  });

  test('test_6_a_tone_choice_with_no_changes_shows_a_notice', () => {
    for (const sceneId of snapshot().document.scene_order) {
      for (const line of snapshot().document.scenes[sceneId]?.lines ?? []) {
        editLine(sceneId, line.id, '다른 대사');
      }
    }

    setRegister('neutral');

    expect(snapshot().tone).toBeNull();
    expect(snapshot().error).toBe('script.tone.none');
    expect(snapshot().document.register).toBe('friendly');
  });

  test('test_8_a_dropped_scene_id_is_not_reused_and_its_mark_clears', async () => {
    setSceneCount(8);
    const eighth = snapshot().document.scene_order[7];
    expect(eighth).toBeDefined();
    await rewriteScene(eighth!);
    applyRewrite();
    expect(snapshot().changedSceneIds).toContain(eighth);

    setSceneCount(5);
    setSceneCount(8);

    const newEighth = snapshot().document.scene_order[7];
    expect(newEighth).not.toBe(eighth);
    expect(snapshot().changedSceneIds).not.toContain(eighth);
    expect(snapshot().targetSceneId).toBeNull();
    expect(snapshot().document.scenes[newEighth!]?.lines[0]?.display_text).toBe('');
  });

  test('test_9_the_contract_counts_code_points', async () => {
    const id = firstSceneId();
    const line = snapshot().document.scenes[id]?.lines[0];
    const emoji = '😀'.repeat(151);
    expect(emoji.length).toBe(302);

    editLine(id, line!.id, emoji);

    expect(snapshot().nextBlockedReason).toBeNull();
    await confirmScript();
    expect(snapshot().confirmed).toBe(true);
  });

  test('test_2_the_target_scene_lives_in_the_script_state', async () => {
    const id = firstSceneId();
    await rewriteScene(id);

    expect(snapshot().targetSceneId).toBe(id);
    dismissRewrite();
    clearTarget();
    expect(snapshot().targetSceneId).toBeNull();
  });
});
