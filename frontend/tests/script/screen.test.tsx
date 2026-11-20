import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { LocaleProvider } from '@/shared/lib/i18n/locale';
import { recommendedSceneCount } from '@/features/concept/model';
import { MockScriptApi } from '@/features/script/api';
import { configureScriptSceneCounts, DURATIONS } from '@/features/script/model';
import { ScriptScreen } from '@/features/script/script-screen';
import {
  applyTone,
  configureScriptApi,
  editLine,
  ensureScript,
  focusScene,
  getScriptSnapshot,
  rewriteScene,
  setRegister,
  setLength,
  setSceneCount,
} from '@/features/script/store';
import type { ScriptSnapshot } from '@/features/script/types';

let api: MockScriptApi;

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

async function open(props: { onNext?: () => void } = {}): Promise<void> {
  await ensureScript('ko');
  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <ScriptScreen {...props} />
    </LocaleProvider>,
  );
  await screen.findByRole('heading', { name: '대본' });
}

beforeEach(async () => {
  configureScriptSceneCounts(DURATIONS.map((seconds) => recommendedSceneCount(seconds)));
  api = new MockScriptApi({ rewriteDelayMs: 60 });
  configureScriptApi(api);
});

afterEach(cleanup);

describe('script screen', () => {
  test('test_10a_the_document_head_and_every_card_show_the_settled_controls', async () => {
    await open();

    expect(screen.getByRole('combobox', { name: '길이' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: '장면 수' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: '말투' })).toBeTruthy();

    const cards = document.querySelectorAll('[data-slot="script-scene"]');
    expect(cards).toHaveLength(5);
    const first = cards[0] as HTMLElement;
    expect(within(first).getByRole('button', { name: '장면 1 순서 바꾸기' })).toBeTruthy();
    expect(
      (within(first).getByRole('button', { name: '위로 옮기기' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (within(first).getByRole('button', { name: '아래로 옮기기' }) as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(within(first).getByRole('button', { name: '장면 1 메뉴' })).toBeTruthy();
    expect(
      (within(first).getByRole('button', { name: 'AI로 다시 쓰기' }) as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(within(first).getByText(/약 \d+초/u)).toBeTruthy();

    const next = screen.getByRole('button', { name: '이대로 영상 만들기' });
    expect((next as HTMLButtonElement).disabled).toBe(false);
    expect(document.querySelectorAll('[data-slot="script-next"]')).toHaveLength(1);

    const card = first.querySelector('.script-card');
    const rewrite = within(first).getByRole('button', { name: 'AI로 다시 쓰기' });
    expect(card?.contains(rewrite)).toBe(false);
    expect(first.contains(rewrite)).toBe(true);
    expect(document.querySelector('[data-slot="script-fade"]')).toBeNull();
  });

  test('test_26_the_tone_preview_shows_old_and_new_lines_and_apply_marks_scenes', async () => {
    await open();
    const before = document.querySelector('[data-slot="script-summary"]')?.textContent;

    act(() => setRegister('neutral'));

    await waitFor(() =>
      expect(document.querySelectorAll('[data-slot="script-tone-preview"]')).toHaveLength(5),
    );
    const firstPreview = document.querySelector('[data-slot="script-tone-preview"]') as HTMLElement;
    expect(firstPreview.querySelector('del')?.textContent).toContain('확인해요');
    expect(firstPreview.textContent).toContain('확인합니다');
    expect(snapshot().document.register).toBe('friendly');
    expect(snapshot().tone?.to).toBe('neutral');
    expect(
      (screen.getByRole('button', { name: '이대로 영상 만들기' }) as HTMLButtonElement).disabled,
    ).toBe(true);

    act(() => applyTone());

    await waitFor(() =>
      expect(document.querySelectorAll('[data-slot="script-tone-preview"]')).toHaveLength(0),
    );
    expect(screen.getAllByText('바뀜')).toHaveLength(5);
    expect(snapshot().document.register).toBe('neutral');
    expect(document.querySelector('[data-slot="script-summary"]')?.textContent).not.toBe(before);
  });

  test('test_8a_the_rewrite_review_applies_in_the_scene_and_undoes_once', async () => {
    await open();
    const id = firstSceneId();
    const original = snapshot().document.scenes[id]?.lines[0]?.display_text ?? '';

    await act(async () => {
      await rewriteScene(id);
    });

    expect(document.querySelector('[data-slot="script-review"]')).not.toBeNull();
    expect(document.querySelector('[data-slot="script-undo"]')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '바꾸기' }));

    await waitFor(() => expect(screen.getByRole('button', { name: '되돌리기' })).toBeTruthy());
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text.startsWith('다시 말하면, ')).toBe(
      true,
    );

    fireEvent.click(screen.getByRole('button', { name: '되돌리기' }));
    await waitFor(() =>
      expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe(original),
    );
  });

  test('test_8a_retry_asks_for_another_rewrite', async () => {
    await open();
    const id = firstSceneId();

    await act(async () => {
      await rewriteScene(id);
    });
    const first = snapshot().rewrite?.after[0];

    fireEvent.click(screen.getByRole('button', { name: '다시' }));

    await waitFor(() =>
      expect(snapshot().rewrite?.after[0]?.startsWith('정리하면, ')).toBe(true),
    );
    expect(snapshot().rewrite?.after[0]).not.toBe(first);
    expect(snapshot().changedSceneIds).toHaveLength(0);
  });

  test('test_2_the_same_card_control_becomes_stop_and_keeps_the_original', async () => {
    api = new MockScriptApi({ rewriteDelayMs: 5000 });
    configureScriptApi(api);
    await open();
    const id = firstSceneId();
    const original = snapshot().document.scenes[id]?.lines[0]?.display_text ?? '';
    let running: Promise<void> = Promise.resolve();

    act(() => {
      running = rewriteScene(id);
    });
    await screen.findByText('고치는 중');

    fireEvent.click(screen.getByRole('button', { name: '멈추기' }));
    await act(async () => {
      await running;
    });

    expect(screen.queryByText('고치는 중')).toBeNull();
    expect(snapshot().document.scenes[id]?.lines[0]?.display_text).toBe(original);
    expect(api.count('cancel')).toBe(1);
  });

  test('test_2_another_scene_stays_editable_while_a_rewrite_runs', async () => {
    await open();
    const second = snapshot().document.scene_order[1];
    expect(second).toBeDefined();
    const scene2 = document.querySelectorAll<HTMLElement>('[data-slot="script-scene"]')[1];
    expect(scene2).toBeDefined();
    const rewrite = within(scene2).getByRole('button', { name: 'AI로 다시 쓰기' });
    act(() => {
      fireEvent.click(rewrite);
    });

    const box = screen.getByRole('textbox', { name: '장면 1 대사 1' });
    expect((box as HTMLTextAreaElement).disabled).toBe(false);
    fireEvent.change(box, { target: { value: '다른 장면은 계속 고칠 수 있어요.' } });

    const workingBox = screen.getByRole('textbox', { name: '장면 2 대사 1' });
    expect((workingBox as HTMLTextAreaElement).disabled).toBe(true);

    expect(snapshot().document.scenes[firstSceneId()]?.lines[0]?.display_text).toBe(
      '다른 장면은 계속 고칠 수 있어요.',
    );

    await act(async () => {
      await waitFor(() => expect(snapshot().workingSceneId).toBeNull());
    });
  });

  test('test_2_enter_makes_the_break_and_no_other_break_appears', async () => {
    await open();
    const box = screen.getByRole('textbox', { name: '장면 1 대사 1' });

    fireEvent.change(box, { target: { value: '첫 줄\n둘째 줄' } });

    expect(snapshot().document.scenes[firstSceneId()]?.lines[0]?.display_text).toBe(
      '첫 줄\n둘째 줄',
    );
    expect(snapshot().document.scenes[firstSceneId()]?.lines[0]?.speech_text).toBe(
      '첫 줄\n둘째 줄',
    );

    fireEvent.change(box, { target: { value: '닫는 따옴표 "이" 앞에서도 줄은 그대로예요.' } });
    const saved = snapshot().document.scenes[firstSceneId()]?.lines[0];
    expect(saved?.display_text).not.toContain('\n');

    const notPrevented = fireEvent.keyDown(box, { key: 'Enter', code: 'Enter' });
    expect(notPrevented).toBe(true);
  });

  test('test_10a_the_scene_count_field_changes_the_cards_and_marks_empty_lines', async () => {
    await open();

    act(() => setSceneCount(8));

    await waitFor(() =>
      expect(document.querySelectorAll('[data-slot="script-scene"]')).toHaveLength(8),
    );
    expect(screen.getByRole('combobox', { name: '장면 수' }).textContent).toContain('8');
    const cards = document.querySelectorAll<HTMLElement>('[data-slot="script-scene"]');
    const emptyCard = cards[5];
    expect(emptyCard).toBeDefined();
    const empty = emptyCard?.querySelector<HTMLTextAreaElement>('[data-slot="script-line-input"]');
    expect(empty).not.toBeNull();
    expect(empty?.value).toBe('');
    expect(empty?.placeholder).toBe('대사를 적어 주세요');
    expect(
      (screen.getByRole('button', { name: '이대로 영상 만들기' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByRole('status').textContent).toContain('빈 대사가 있어요');
  });

  test('test_2_a_line_over_the_contract_limit_shows_the_line_to_fix', async () => {
    await open();
    const box = screen.getByRole('textbox', { name: '장면 1 대사 1' });

    fireEvent.change(box, { target: { value: '가'.repeat(301) } });

    await waitFor(() =>
      expect(document.querySelectorAll('[data-slot="script-line-error"]')).toHaveLength(1),
    );
    expect(screen.getByText('대사는 300자까지 쓸 수 있어요.')).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: '이대로 영상 만들기' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  test('test_2_each_jump_request_scrolls_again', async () => {
    await open();
    const original = HTMLElement.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    const id = firstSceneId();

    try {
      act(() => focusScene(id));
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
      act(() => focusScene(id));
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(2));
    } finally {
      HTMLElement.prototype.scrollIntoView = original;
    }
  });

  test('test_2_the_step_button_confirms_and_opens_the_next_screen', async () => {
    const onNext = vi.fn();
    await open({ onNext });

    fireEvent.click(screen.getByRole('button', { name: '이대로 영상 만들기' }));

    await waitFor(() =>
      expect(screen.getByText('대본을 확인했어요.')).toBeTruthy(),
    );
    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    expect(snapshot().confirmed).toBe(true);
    expect(
      (screen.getByRole('textbox', { name: '장면 1 대사 1' }) as HTMLTextAreaElement).disabled,
    ).toBe(false);
    expect(api.count('confirm')).toBe(1);
    expect(api.count('previews')).toBe(0);
  });

  test('test_2_without_a_step_change_the_confirmed_screen_names_the_step_menu', async () => {
    await open();

    fireEvent.click(screen.getByRole('button', { name: '이대로 영상 만들기' }));

    await waitFor(() => expect(snapshot().confirmed).toBe(true));
    await waitFor(() =>
      expect(screen.getByText('대본을 확인했어요. 단계 메뉴에서 편집으로 넘어가요.')).toBeTruthy(),
    );
    expect(
      (screen.getByRole('button', { name: '이대로 영상 만들기' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole('textbox', { name: '장면 1 대사 1' }) as HTMLTextAreaElement).disabled,
    ).toBe(false);
  });

  test('test_2_the_user_script_is_the_first_line', async () => {
    await ensureScript('ko', {
      id: 'v_user_script',
      topic: '사용자 주제',
      script: '사용자 대본',
    });
    render(
      <LocaleProvider language="ko" setLanguage={() => undefined}>
        <ScriptScreen
          videoId="v_user_script"
          topic="사용자 주제"
          userScript="사용자 대본"
          language="ko"
        />
      </LocaleProvider>,
    );
    await screen.findByRole('heading', { name: '대본' });

    expect(
      (screen.getByRole('textbox', { name: '장면 1 대사 1' }) as HTMLTextAreaElement).value,
    ).toBe('사용자 대본');
  });

  test('test_3_the_interface_language_keeps_the_video_script', async () => {
    await ensureScript('ko', { id: 'v_language', topic: '주제', script: '주제' });
    const view = render(
      <LocaleProvider language="ko" setLanguage={() => undefined}>
        <ScriptScreen videoId="v_language" topic="주제" userScript="주제" language="ko" />
      </LocaleProvider>,
    );
    await screen.findByRole('heading', { name: '대본' });
    fireEvent.change(screen.getByRole('textbox', { name: '장면 1 대사 1' }), {
      target: { value: '언어를 바꿔도 남아요.' },
    });

    view.rerender(
      <LocaleProvider language="en" setLanguage={() => undefined}>
        <ScriptScreen videoId="v_language" topic="주제" userScript="주제" language="ko" />
      </LocaleProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Script' })).toBeTruthy(),
    );
    expect(
      (screen.getByRole('textbox', { name: 'Scene 1 line 1' }) as HTMLTextAreaElement).value,
    ).toBe('언어를 바꿔도 남아요.');
    expect(snapshot().document.language).toBe('ko');
  });

  test('test_10a_the_length_field_applies_the_recommended_count', async () => {
    await open();

    act(() => setLength(120));

    await waitFor(() =>
      expect(document.querySelectorAll('[data-slot="script-scene"]')).toHaveLength(11),
    );
    expect(screen.getByRole('combobox', { name: '길이' }).textContent).toContain('2분');
    expect(screen.getByRole('combobox', { name: '장면 수' }).textContent).toContain('11');
    expect(snapshot().document.scenes[firstSceneId()]?.lines[0]?.display_text).toBeDefined();
    expect(
      (screen.getByRole('button', { name: '이대로 영상 만들기' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  test('test_6_a_tone_choice_with_no_changes_shows_the_existing_notice', async () => {
    await open();
    for (const sceneId of snapshot().document.scene_order) {
      for (const line of snapshot().document.scenes[sceneId]?.lines ?? []) {
        act(() => editLine(sceneId, line.id, '다른 대사'));
      }
    }

    act(() => setRegister('neutral'));

    await waitFor(() =>
      expect(screen.getByRole('status').textContent).toContain('바꿀 문장이 없어요.'),
    );
    expect(snapshot().tone).toBeNull();
    expect(snapshot().document.register).toBe('friendly');
  });

  test('test_9_emoji_lines_count_code_points_in_the_screen_and_the_gate', async () => {
    await open();
    const box = screen.getByRole('textbox', { name: '장면 1 대사 1' });

    fireEvent.change(box, { target: { value: '😀'.repeat(151) } });

    await waitFor(() =>
      expect(document.querySelectorAll('[data-slot="script-line-error"]')).toHaveLength(0),
    );
    expect(
      (screen.getByRole('button', { name: '이대로 영상 만들기' }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  test('test_10a_the_loading_screen_keeps_the_stage_panel', async () => {
    configureScriptApi(new MockScriptApi());
    render(
      <LocaleProvider language="ko" setLanguage={() => undefined}>
        <ScriptScreen />
      </LocaleProvider>,
    );

    const panel = document.querySelector('[data-slot="stage-panel"][data-stage="script"]');
    expect(panel).not.toBeNull();
    expect(within(panel as HTMLElement).getByRole('status')).toBeTruthy();

    await act(async () => {
      await ensureScript('ko');
    });
  });
});
