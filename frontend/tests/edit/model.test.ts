import { describe, expect, test } from 'vitest';

import {
  POSITION_CHOICES,
  adjacentEchoes,
  applyScenePatch,
  breaksFlow,
  changedFields,
  duplicateScene,
  estimatedSeconds,
  insertScene,
  spanSelected,
  stillIsReady,
  stillState,
  toggleSpan,
  wordSpans,
} from '@/features/edit/model';

import { makeBuild, makeVideo } from './fixtures';

describe('edit model', () => {
  test('test_23_a_stale_still_is_not_ready', () => {
    const video = makeVideo();
    const build = makeBuild();
    expect(stillIsReady(build, video.scene_order[0]!)).toBe(true);
    expect(stillIsReady(build, video.scene_order[1]!)).toBe(false);
    expect(stillState(build, video.scene_order[1]!)).toBe('stale');
    expect(stillIsReady(build, video.scene_order[2]!)).toBe(false);
  });

  test('test_23_the_position_menu_keeps_old_anchors_on_the_bottom_row', () => {
    expect(POSITION_CHOICES.map((choice) => choice.anchor)).toEqual([
      'top_left', 'top_center', 'top_right',
      'middle_left', 'middle_center', 'middle_right',
      'left', 'center', 'right',
    ]);
  });

  test('test_23_one_scene_change_keeps_the_other_scenes', () => {
    const video = makeVideo();
    const first = video.scene_order[0]!;
    const second = video.scene_order[1]!;
    const next = applyScenePatch(video, first, { backgroundId: 'bg_stars' });
    expect(next.scenes[first]?.visual?.background_id).toBe('bg_stars');
    expect(next.scenes[second]).toBe(video.scenes[second]);
    expect(next.scene_order).toEqual(video.scene_order);
  });

  test('test_23_a_highlight_toggle_round_trips', () => {
    const words = wordSpans('첫째, 원두가 신선한지 본다.');
    expect(words.map((word) => word.text)).toEqual(['첫째,', '원두가', '신선한지', '본다.']);
    const first = words[0]!;
    const once = toggleSpan([], first);
    expect(spanSelected(once, first)).toBe(true);
    expect(toggleSpan(once, first)).toEqual([]);
  });

  test('test_23_highlight_offsets_count_code_points', () => {
    const words = wordSpans('🛠 도구');
    expect(words).toEqual([
      { start: 0, end: 1, text: '🛠' },
      { start: 2, end: 4, text: '도구' },
    ]);
  });

  test('test_23_duplicating_a_scene_repairs_internal_line_references', () => {
    const video = makeVideo();
    const sourceId = video.scene_order[0]!;
    const source = video.scenes[sourceId]!;
    source.beat_label = '🛠'.repeat(40);
    const lineId = source.lines[0]!.id;
    source.visual = {
      ...source.visual!,
      elements: [{ id: 'e_0element0000000000000000', kind: 'label', value: '표시', anchor: 'center', reveal_line_id: lineId }],
      sfx: [{ sfx_id: { id: 'pop', revision: '1'.repeat(64) }, line_id: lineId, at: 'start', offset_ms: 0 }],
    };
    const scene = duplicateScene(video, sourceId, 's_0copy00000000000000000000');
    expect(scene?.id).toBe('s_0copy00000000000000000000');
    const copied = scene!.lines[0]!.id;
    expect(copied).not.toBe(lineId);
    expect(scene?.visual?.elements[0]?.reveal_line_id).toBe(copied);
    expect(scene?.visual?.sfx[0]?.line_id).toBe(copied);
    expect(scene?.beat_label).toBe('🛠'.repeat(40));
  });

  test('test_23_an_added_scene_sits_right_after_the_current_one', () => {
    const video = makeVideo();
    const scene = duplicateScene(video, video.scene_order[1]!, 's_0copy00000000000000000000');
    expect(scene).not.toBeNull();
    if (scene === null) return;
    const inserted = insertScene(video, video.scene_order[1]!, scene);
    expect(inserted.order).toEqual([
      video.scene_order[0],
      video.scene_order[1],
      scene.id,
      video.scene_order[2],
    ]);
  });

  test('test_23_the_flow_warns_when_the_hook_leaves_first', () => {
    const video = makeVideo();
    expect(breaksFlow(video, video.scene_order)).toBe(false);
    expect(
      breaksFlow(video, [video.scene_order[1]!, video.scene_order[0]!, video.scene_order[2]!]),
    ).toBe(true);
  });

  test('test_23_the_flow_warns_when_numbered_scenes_swap', () => {
    const video = makeVideo();
    const [hook, first, second] = video.scene_order;
    expect(breaksFlow(video, [hook!, second!, first!])).toBe(true);
  });

  test('test_10a_the_scene_length_follows_the_spoken_text', () => {
    const video = makeVideo();
    expect(estimatedSeconds(video.scenes[video.scene_order[0]!]!)).toBe(3);
    expect(estimatedSeconds(null)).toBe(0);
  });

  test('test_26_an_old_word_in_a_neighbouring_scene_warns', () => {
    const video = makeVideo();
    const echoes = adjacentEchoes(
      video,
      video.scene_order[0]!,
      '커피를 고르는 기준은 세 가지뿐이다.',
      '음료를 고르는 기준은 세 가지뿐이다.',
    );
    expect(echoes).toEqual([video.scene_order[1]]);
  });

  test('test_10a_a_change_lights_only_the_cells_it_touched', () => {
    const video = makeVideo();
    const before = video.scenes[video.scene_order[0]!]!;
    const after = structuredClone(before);
    expect(changedFields(before, after)).toEqual([]);

    after.visual!.background_id = 'bg_city';
    after.visual!.characters![0]!.anchor = 'top_right';
    after.lines[0]!.display_text = '다른 문장이다.';
    expect(changedFields(before, after)).toEqual(['background', 'position', 'lines']);

    after.lines[0]!.highlight = [{ start: 0, end: 2 }];
    expect(changedFields(before, after)).toContain('highlight');
    expect(changedFields(undefined, after)).toEqual([]);
  });
});
