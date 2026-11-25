import { expect, test } from 'vitest';

import { createMockConceptApi } from '@/features/concept/api';
import { conceptGreeting } from '@/features/concept/greeting';
import type { Settings } from '@/features/concept/types';
import { translate } from '@/shared/lib/i18n/catalog';

function t(key: string, vars?: Record<string, string | number>): string {
  return translate('ko', key, vars);
}

async function settings(): Promise<Settings> {
  const api = createMockConceptApi();
  const document = await api.create({ topic: '합성 주제', language: 'ko', duration: 30 });
  return document.settings;
}

test('test_5_the_first_reply_names_picked_values_and_defaults', async () => {
  const value = await settings();
  expect(conceptGreeting(value, t)).toBe([
    '이야기 방식은 딱 3가지만으로 골랐어요.',
    '길이는 30초, 장면은 5개로 했어요.',
    '그림체와 캐릭터는 기본값이에요.',
    '바꾸고 싶은 것만 말하거나 눌러 주세요.',
  ].join(' '));
});

test('test_5_the_first_reply_names_values_the_draft_picked', async () => {
  const value = await settings();
  value.format.story_structure = 'hypothetical';
  value.format.card_id = 'what_if';
  value.origins['/format/story_structure'] = 'llm';
  value.origins['/format/card_id'] = 'llm';
  value.origins['/visual/art_style'] = 'llm';
  value.origins['/visual/character'] = 'llm';
  expect(conceptGreeting(value, t)).toBe([
    '이야기 방식은 만약 ~라면?으로 골랐어요.',
    '길이는 30초, 장면은 5개로 했어요.',
    '그림체는 픽셀으로 골랐어요.',
    '캐릭터는 기본 몸으로 골랐어요.',
    '바꾸고 싶은 것만 말하거나 눌러 주세요.',
  ].join(' '));
});

test('test_5_the_first_reply_calls_only_the_untouched_value_a_default', async () => {
  const value = await settings();
  value.origins['/visual/art_style'] = 'user';
  expect(conceptGreeting(value, t)).toContain('그림체는 픽셀으로 골랐어요.');
  expect(conceptGreeting(value, t)).toContain('캐릭터는 기본값이에요.');
});
