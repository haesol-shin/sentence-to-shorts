import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { ConceptScreen } from '@/features/concept/concept-screen';
import { createMockConceptApi, type MockConceptApi } from '@/features/concept/api';
import {
  applyConceptPlan,
  beginConcept,
  chooseConcept,
  configureConceptApi,
  getConceptSnapshot,
  reloadConcept,
  reloadConceptCatalog,
  resetConceptSessions,
  sendConcept,
} from '@/features/concept/store';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

let api: MockConceptApi;

function Composer() {
  return <div />;
}

function renderConcept() {
  return render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <ConceptScreen ComposerComponent={Composer} />
    </LocaleProvider>,
  );
}

function snapshot() {
  const value = getConceptSnapshot();
  if (value === null) throw new Error('No active concept session');
  return value;
}

function storedDocument() {
  const stored = api.sessions.get(snapshot().document.id);
  if (stored === undefined) throw new Error('The mock session is missing');
  return stored;
}

/** Writes the draft's picks into the stored document and loads them again. */
async function fillDraft(): Promise<void> {
  const stored = storedDocument();
  stored.settings.format.story_structure = 'hypothetical';
  stored.settings.format.card_id = 'what_if';
  stored.settings.origins['/format/story_structure'] = 'llm';
  stored.settings.origins['/format/card_id'] = 'llm';
  stored.settings.target_duration_s = 60;
  stored.settings.origins['/target_duration_s'] = 'llm';
  stored.settings.format.register = 'casual';
  stored.settings.origins['/format/register'] = 'card';
  stored.settings.format.scene_count = 8;
  stored.settings.origins['/format/scene_count'] = 'card';
  const flat = api.catalogValue().styles[1]?.ref;
  if (flat === undefined) throw new Error('The mock catalog has no second style');
  stored.settings.visual.art_style = flat;
  stored.settings.origins['/visual/art_style'] = 'llm';
  await reloadConcept(stored.id);
}

function markOf(selector: string): string | null {
  return document.querySelector(selector)?.getAttribute('data-changed') ?? null;
}

beforeEach(async () => {
  resetConceptSessions();
  api = createMockConceptApi();
  configureConceptApi(api);
  await beginConcept({ topic: '합성 주제', language: 'ko', duration: 30 });
  await reloadConceptCatalog();
});

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

test('test_5_the_draft_filled_controls_carry_the_changed_mark_once', async () => {
  await fillDraft();

  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });

  expect(markOf('.concept-card-slot[data-card="what_if"]')).not.toBeNull();
  expect(markOf('[aria-label="플랫"]')).not.toBeNull();
  expect(screen.getByRole('combobox', { name: '목표 길이' }).closest('.concept-tune-slot')
    ?.getAttribute('data-changed')).not.toBeNull();
  // The draft's card fills the scene count even though its origin is `card`.
  expect(screen.getByRole('combobox', { name: '장면 수' }).closest('.concept-tune-slot')
    ?.getAttribute('data-changed')).not.toBeNull();
  // A card the draft did not pick stays unmarked.
  expect(markOf('.concept-card-slot[data-card="just_three"]')).toBeNull();
});

test('test_5_a_user_pick_never_carries_the_changed_mark', async () => {
  await fillDraft();

  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  expect(markOf('.concept-card-slot[data-card="what_if"]')).not.toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '딱 3가지만' }));

  expect(markOf('.concept-card-slot[data-card="just_three"]')).toBeNull();
  expect(markOf('.concept-card-slot[data-card="what_if"]')).toBeNull();

  // The picked card's own values replace the draft's marks in the board too.
  fireEvent.click(screen.getByRole('button', { name: '딱 3가지만 세부 조정' }));
  expect(screen.getByRole('combobox', { name: '말투' }).closest('.concept-tune-slot')
    ?.getAttribute('data-changed')).toBeNull();
  expect(screen.getByRole('combobox', { name: '유머' }).closest('.concept-tune-slot')
    ?.getAttribute('data-changed')).toBeNull();
});

test('test_5_a_remount_does_not_replay_the_changed_mark', async () => {
  await fillDraft();

  const first = renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  expect(markOf('.concept-card-slot[data-card="what_if"]')).not.toBeNull();

  first.unmount();
  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });

  expect(markOf('.concept-card-slot[data-card="what_if"]')).toBeNull();
  expect(markOf('[aria-label="플랫"]')).toBeNull();
});

test('test_5_a_second_change_restarts_the_mark', async () => {
  await fillDraft();

  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  const duration = () => screen.getByRole('combobox', { name: '목표 길이' })
    .closest('.concept-tune-slot')?.getAttribute('data-changed') ?? null;
  const first = duration();
  expect(first).not.toBeNull();

  await act(async () => {
    await sendConcept('2분으로 해 줘');
    if (snapshot().pending !== null) {
      await applyConceptPlan();
    }
  });

  expect(duration()).not.toBeNull();
  expect(duration()).not.toBe(first);
});

test('test_5_a_replacement_pick_clears_the_old_style_mark', async () => {
  // The draft marks the flat copy; the pixel pick then needs a character
  // replacement, and approving it must consume the flat mark.
  const flat = api.catalogValue().styles[1];
  if (flat === undefined) throw new Error('The mock catalog has no second style');
  await fillDraft();

  const catalog = snapshot().catalog;
  const pixel = catalog?.styles.find((style) => style.ref.id === 'pixel');
  if (pixel === undefined) throw new Error('The mock catalog has no pixel style');
  const body = pixel.manifest.assets.find((asset) => asset.kind === 'part' && asset.slot === 'body');
  if (body === undefined) throw new Error('The pixel style has no body asset');
  body.id = 'body_other';
  pixel.manifest.rig.slots.body = ['body_other'];

  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  expect(markOf(`[aria-label="${flat.manifest.label.ko}"]`)).not.toBeNull();

  chooseConcept('/visual/art_style', pixel.ref);
  expect(snapshot().pending?.source).toBe('direct');
  // The replacement candidate is valid against the store catalog; the mock
  // save would check its unmodified copy, which is not the point of this test.
  api.save = (videoId, settings) => Promise.resolve({
    ...snapshot().document,
    id: videoId,
    settings,
    revision: snapshot().document.revision + 1,
  });
  await act(async () => {
    await applyConceptPlan();
  });

  expect(markOf('[aria-label="픽셀"]')).toBeNull();
  expect(snapshot().changedPaths.map((entry) => entry.path)).not.toContain('/visual/art_style');

  // A later draft read must not take the approved replacement back to the
  // style the draft wrote.
  const stored = api.sessions.get(snapshot().document.id);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.visual.art_style = flat.ref;
  await act(async () => {
    await reloadConcept(stored.id);
  });
  expect(snapshot().document.settings.visual.art_style.id).toBe('pixel');
});

test('test_5_a_character_slot_change_marks_only_its_field', async () => {
  await reloadConceptCatalog();
  const stored = storedDocument();
  const character = stored.settings.visual.character;
  if (character === null) throw new Error('The mock session has no character');
  const catalog = snapshot().catalog;
  if (catalog === null) throw new Error('The mock catalog is missing');
  const style = catalog.styles.find((entry) => entry.ref.id === stored.settings.visual.art_style.id);
  if (style === undefined) throw new Error('The mock style is missing');
  const template = style.manifest.assets.find((entry) => entry.kind === 'part');
  if (template === undefined) throw new Error('The mock style has no part asset');
  style.manifest.assets.push({ ...template, id: 'hat_test', slot: 'hat' });
  style.manifest.rig.slots.hat.push('hat_test');
  character.slots.hat = 'hat_test';
  await reloadConcept(stored.id);

  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  const section = screen.getByRole('heading', { name: '캐릭터' }).closest('section');
  if (section === null) throw new Error('The character section is missing');
  fireEvent.click(within(section).getAllByRole('button', { name: /세부 조정/ })[0]!);

  const changed = (name: string) => screen.getByRole('combobox', { name })
    .closest('.concept-tune-slot')?.getAttribute('data-changed') ?? null;
  expect(changed('모자')).not.toBeNull();
  for (const name of ['얼굴', '머리', '옷', '소품']) {
    expect(changed(name)).toBeNull();
  }
});

test('test_5_undo_drops_the_mark_with_the_restored_value', async () => {
  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  const duration = () => screen.getByRole('combobox', { name: '목표 길이' })
    .closest('.concept-tune-slot')?.getAttribute('data-changed') ?? null;

  await act(async () => {
    await sendConcept('2분으로 해 줘');
    if (snapshot().pending !== null) {
      await applyConceptPlan();
    }
  });
  expect(duration()).not.toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '되돌리기' }));

  expect(duration()).toBeNull();
});

test('test_5_a_closed_board_does_not_replay_its_mark_on_reopen', async () => {
  await fillDraft();
  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  const toggle = screen.getByRole('button', { name: '만약 ~라면? 세부 조정' });
  const register = () => screen.getByRole('combobox', { name: '말투' })
    .closest('.concept-tune-slot')?.getAttribute('data-changed') ?? null;

  fireEvent.click(toggle);
  expect(register()).not.toBeNull();

  fireEvent.click(toggle);
  fireEvent.click(toggle);

  await waitFor(() => expect(register()).toBeNull());
});

test('test_5_a_value_change_does_not_replay_the_hidden_board_mark', async () => {
  await fillDraft();
  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  fireEvent.click(screen.getByRole('button', { name: '만약 ~라면? 세부 조정' }));
  const register = () => screen.getByRole('combobox', { name: '말투' })
    .closest('.concept-tune-slot')?.getAttribute('data-changed') ?? null;
  expect(register()).not.toBeNull();

  // Another value changes the active card, so the shown board goes away
  // without the close button.
  await act(async () => {
    chooseConcept('/format/card_id', 'just_three');
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(screen.queryByRole('combobox', { name: '말투' })).toBeNull();

  await act(async () => {
    chooseConcept('/format/card_id', 'what_if');
  });

  await waitFor(() => expect(register()).toBeNull());
});
test('test_5_a_new_mark_survives_the_old_board_closing', async () => {
  const getJob = api.getJob.bind(api);
  api.getJob = async (jobId) => {
    const job = await getJob(jobId);
    const plan = job.result?.plan;
    if (plan !== undefined && plan !== null) {
      plan.ops = [
        ...plan.ops,
        { op: 'set', path: '/format/card_id', value: 'just_three', origin: 'user' },
      ];
    }
    return job;
  };
  await fillDraft();
  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  fireEvent.click(screen.getByRole('button', { name: '만약 ~라면? 세부 조정' }));
  const register = () => screen.getByRole('combobox', { name: '말투' })
    .closest('.concept-tune-slot')?.getAttribute('data-changed') ?? null;
  expect(register()).not.toBeNull();

  // One chat update changes the card and the tone; the old board never showed
  // the new tone version, so its close must not consume it.
  await act(async () => {
    await sendConcept('말투는 중립으로');
    if (snapshot().pending !== null) {
      await applyConceptPlan();
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(screen.queryByRole('combobox', { name: '말투' })).toBeNull();

  await act(async () => {
    chooseConcept('/format/card_id', 'what_if');
  });
  await waitFor(() => expect(register()).not.toBeNull());
});

test('test_5_a_width_hidden_board_does_not_replay_its_mark', async () => {
  const callbacks: (() => void)[] = [];
  vi.stubGlobal('ResizeObserver', class {
    private callback: () => void;
    constructor(callback: () => void) {
      this.callback = callback;
      callbacks.push(callback);
    }
    observe() { this.callback(); }
    unobserve() {}
    disconnect() {}
  });
  await fillDraft();
  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  const grid = document.querySelector<HTMLElement>('.concept-card-grid');
  if (grid === null) throw new Error('The card grid is missing');
  let width = 900;
  Object.defineProperty(grid, 'clientWidth', { configurable: true, get: () => width });
  await act(async () => {
    for (const callback of callbacks) callback();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  fireEvent.click(screen.getByRole('button', { name: '○○로 치면 세부 조정' }));
  const register = () => screen.getByRole('combobox', { name: '말투' })
    .closest('.concept-tune-slot')?.getAttribute('data-changed') ?? null;
  await act(async () => {
    await sendConcept('말투는 중립으로');
    if (snapshot().pending !== null) {
      await applyConceptPlan();
    }
  });
  expect(register()).not.toBeNull();

  await act(async () => {
    width = 320;
    for (const callback of callbacks) callback();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(screen.queryByRole('combobox', { name: '말투' })).toBeNull();

  await act(async () => {
    width = 900;
    for (const callback of callbacks) callback();
  });
  await waitFor(() => expect(register()).toBeNull());
});
test('test_5_a_character_board_does_not_consume_the_body_card_mark', async () => {
  await reloadConceptCatalog();
  const stored = storedDocument();
  const character = stored.settings.visual.character;
  if (character === null) throw new Error('The mock session has no character');
  const catalog = snapshot().catalog;
  if (catalog === null) throw new Error('The mock catalog is missing');
  const style = catalog.styles.find((entry) => entry.ref.id === stored.settings.visual.art_style.id);
  if (style === undefined) throw new Error('The mock style is missing');
  const template = style.manifest.assets.find((entry) => entry.kind === 'part');
  if (template === undefined) throw new Error('The mock style has no part asset');
  style.manifest.assets.push({ ...template, id: 'body_test', slot: 'body' });
  style.manifest.rig.slots.body.push('body_test');
  character.slots.body = 'body_test';
  await reloadConcept(stored.id);

  renderConcept();
  await screen.findByRole('heading', { name: '컨셉' });
  const card = document.querySelector('.concept-card-slot[data-card="character-body_test"]');
  expect(card?.getAttribute('data-changed')).not.toBeNull();
  if (card === null) throw new Error('The character card is missing');
  fireEvent.click(within(card as HTMLElement).getByRole('button', { name: /세부 조정/ }));
  fireEvent.click(within(card as HTMLElement).getByRole('button', { name: /세부 조정/ }));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(card?.getAttribute('data-changed')).not.toBeNull();
});
