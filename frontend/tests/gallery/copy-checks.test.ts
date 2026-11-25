import { describe, expect, test } from 'vitest';

import { checkCopy, errorLine, placeholders } from '../../src/gallery/copy/checks';

const base = {
  originalKo: '파일 {name}을 지워요',
  originalEn: 'Remove {name}',
  ko: '파일 {name}을 지워요',
  en: 'Remove {name}',
  koKeys: ['a', 'b'],
  enKeys: ['a', 'b'],
};

describe('copy save checks', () => {
  test('test_10a_copy_rejects_an_empty_value', () => {
    const errors = checkCopy({ ...base, ko: '   ' });
    expect(errors.map((error) => error.code)).toEqual(['empty-ko']);
    expect(errorLine(errors)).toContain('한국어 값이 비었어요');

    const english = checkCopy({ ...base, en: '' });
    expect(english.map((error) => error.code)).toEqual(['empty-en']);
  });

  test('test_10a_copy_keeps_every_original_placeholder', () => {
    const errors = checkCopy({ ...base, ko: '파일을 지워요' });
    expect(errors.map((error) => error.code)).toEqual(['placeholder-ko']);
    expect(errorLine(errors)).toBe('저장 안 됨: {name}이 빠졌어요');

    const english = checkCopy({ ...base, en: 'Remove it' });
    expect(english.map((error) => error.code)).toEqual(['placeholder-en']);
    expect(errorLine(english)).toContain('영어 값에');
  });

  test('test_10a_copy_requires_the_same_key_set_in_both_files', () => {
    const errors = checkCopy({ ...base, koKeys: ['a', 'b', 'c'], enKeys: ['a', 'b'] });
    expect(errors.map((error) => error.code)).toEqual(['key-set']);
    expect(errorLine(errors)).toContain('한국어에만 1개');
  });

  test('test_10a_copy_passes_a_value_that_keeps_the_placeholders', () => {
    const errors = checkCopy({ ...base, ko: '파일 {name}을 지금 지워요', en: 'Remove {name} now' });
    expect(errors).toEqual([]);
    expect(errorLine(errors)).toBe('검사 통과');
  });

  test('test_10a_copy_lists_each_placeholder_once', () => {
    expect(placeholders('{a}와 {b}, 다시 {a}')).toEqual(['a', 'b']);
  });
});
