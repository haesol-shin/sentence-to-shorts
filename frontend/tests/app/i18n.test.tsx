import { expect, test } from 'vitest';

import { catalogKeys, catalogNamespaces, LANGUAGES, translate } from '@/shared/lib/i18n/catalog';

const NAMESPACES = ['audio', 'concept', 'edit', 'errors', 'export', 'script', 'shell'];

test('test_16_both_languages_define_the_same_keys', () => {
  expect(catalogKeys('en')).toEqual(catalogKeys('ko'));
});

test('test_16_every_screen_language_has_every_namespace', () => {
  for (const language of LANGUAGES) {
    expect(catalogNamespaces(language)).toEqual(NAMESPACES);
  }
});

test('test_16_every_entry_has_text_in_both_languages', () => {
  for (const language of LANGUAGES) {
    for (const key of catalogKeys(language)) {
      expect(translate(language, key)).not.toBe('');
      expect(translate(language, key)).not.toBe(key);
    }
  }
});

test('test_16_a_server_message_key_reaches_its_english_text', () => {
  expect(translate('en', 'errors.error.revision_conflict')).toBe(
    'Something changed elsewhere first. The newest version is loaded.',
  );
});

test('test_16_an_unknown_key_stays_visible', () => {
  expect(translate('ko', 'shell.does.not.exist')).toBe('shell.does.not.exist');
});

test('test_16_a_value_is_filled_into_the_sentence', () => {
  expect(translate('ko', 'shell.first.cardChip', { label: '딱 3가지만' })).toBe('카드: 딱 3가지만');
});
