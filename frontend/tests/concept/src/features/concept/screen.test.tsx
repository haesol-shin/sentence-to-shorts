import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test } from 'vitest';

import { ConceptScreen } from '@/features/concept/concept-screen';
import { createMockConceptApi, type MockConceptApi } from '@/features/concept/api';
import {
  beginConcept,
  configureConceptApi,
  getConceptSnapshot,
  reloadConcept,
  reloadConceptCatalog,
  resetConceptSessions,
} from '@/features/concept/store';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

let api: MockConceptApi;

function Composer() {
  return <div />;
}

beforeEach(async () => {
  resetConceptSessions();
  api = createMockConceptApi();
  configureConceptApi(api);
  await beginConcept({ topic: '합성 주제', language: 'ko', duration: 30 });
  await reloadConceptCatalog();
});

afterEach(cleanup);

test('test_5_the_draft_filled_controls_carry_the_changed_mark_once', async () => {
  const before = getConceptSnapshot();
  if (before === null) throw new Error('No active concept session');
  const stored = api.sessions.get(before.document.id);
  if (stored === undefined) throw new Error('The mock session is missing');
  stored.settings.format.story_structure = 'hypothetical';
  stored.settings.format.card_id = 'what_if';
  stored.settings.origins['/format/story_structure'] = 'llm';
  stored.settings.origins['/format/card_id'] = 'llm';
  stored.settings.target_duration_s = 60;
  stored.settings.origins['/target_duration_s'] = 'llm';
  const flat = api.catalogValue().styles[1]?.ref;
  if (flat === undefined) throw new Error('The mock catalog has no second style');
  stored.settings.visual.art_style = flat;
  stored.settings.origins['/visual/art_style'] = 'llm';
  await reloadConcept(before.document.id);

  render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <ConceptScreen ComposerComponent={Composer} />
    </LocaleProvider>,
  );
  await screen.findByRole('heading', { name: '컨셉' });

  expect(document.querySelector('.concept-card-slot[data-card="what_if"]')?.getAttribute('data-changed'))
    .toBe('true');
  expect(document.querySelector('[aria-label="플랫"]')?.getAttribute('data-changed')).toBe('true');
  expect(screen.getByRole('combobox', { name: '목표 길이' }).closest('.concept-tune-slot')
    ?.getAttribute('data-changed')).toBe('true');
  // A value the draft did not touch stays unmarked.
  expect(screen.getByRole('combobox', { name: '장면 수' }).closest('.concept-tune-slot')
    ?.getAttribute('data-changed')).toBeNull();
});
