import { expect, test } from 'vitest';

import { CAPTION_MODES, CAPTION_POSITIONS } from '@/features/edit/captions/model';
import { MOODS } from '@/features/edit/sound/model';
import { catalogKeys, LANGUAGES, translate } from '@/shared/lib/i18n/catalog';

test('test_24_the_sound_and_caption_words_live_in_audio_json_only', () => {
  for (const language of LANGUAGES) {
    const keys = catalogKeys(language);
    const edit = keys.filter((key) => key.startsWith('edit.'));
    expect(edit.filter((key) => /^edit\.(sound|caption|bgm|voice|mood|picker|preview\.(listen|stop))/u.test(key))).toEqual([]);
    expect(edit.filter((key) => key.endsWith('Pending'))).toEqual([]);
    expect(keys.filter((key) => key.startsWith('audio.')).length).toBeGreaterThan(40);
  }
  expect(translate('ko', 'edit.tabs.soundPending')).toBe('edit.tabs.soundPending');
  expect(translate('ko', 'edit.tabs.captionsPending')).toBe('edit.tabs.captionsPending');
});

test('test_24_every_mood_and_caption_choice_has_its_words_in_both_languages', () => {
  for (const language of LANGUAGES) {
    for (const mood of MOODS) {
      expect(translate(language, `audio.mood.${mood}`)).not.toBe(`audio.mood.${mood}`);
    }
    for (const mode of CAPTION_MODES) {
      expect(translate(language, `audio.caption.mode.${mode}`)).not.toBe(`audio.caption.mode.${mode}`);
      expect(translate(language, `audio.caption.modeHelp.${mode}`)).not.toBe(
        `audio.caption.modeHelp.${mode}`,
      );
    }
    for (const position of CAPTION_POSITIONS) {
      const key = `audio.caption.position.${position}`;
      expect(translate(language, key)).not.toBe(key);
    }
  }
});

test('test_24_the_caption_modes_are_three_in_code_and_no_list_file_exists', () => {
  expect(CAPTION_MODES).toEqual(['sentence', 'phrase', 'typewriter']);
  const files = import.meta.glob('/src/features/edit/captions/**/*.{json,yaml,yml,toml}');
  expect(Object.keys(files)).toEqual([]);
});

test('caption locale keys match across languages', () => {
  const ko = catalogKeys('ko').filter((key) => key.startsWith('audio.caption.'));
  const en = catalogKeys('en').filter((key) => key.startsWith('audio.caption.'));
  expect([...en].sort()).toEqual([...ko].sort());
});

test('test_24_no_caption_word_of_the_second_layer_lives_in_edit_json', () => {
  for (const language of LANGUAGES) {
    const edit = catalogKeys(language).filter((key) => key.startsWith('edit.'));
    expect(edit.filter((key) => /^edit\.caption|translation|layer|overlap|extra/iu.test(key))).toEqual([]);
  }
});
