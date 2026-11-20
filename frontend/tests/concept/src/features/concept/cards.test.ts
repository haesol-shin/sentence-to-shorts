import { expect, test } from 'vitest';

import {
  CARD_DESCRIPTION_LIMIT,
  CARD_TITLE_LIMIT,
  cardColumns,
  clampCardText,
  visibleCardCount,
} from '@/features/concept/cards';

test('test_4_card_rows_follow_the_card_width_and_stop_after_two_rows', () => {
  expect(cardColumns(904)).toBe(4);
  expect(cardColumns(704)).toBe(3);
  expect(cardColumns(444)).toBe(2);
  expect(cardColumns(200)).toBe(1);
  expect(visibleCardCount(3, 3)).toBe(3);
  expect(visibleCardCount(6, 3)).toBe(6);
  expect(visibleCardCount(7, 3)).toBe(6);
  expect(visibleCardCount(5, 2)).toBe(4);
});

test('test_4_card_text_fits_two_title_lines_and_two_description_lines', () => {
  const title = '아주 긴 그림체 이름이 카드 제목 자리를 넘어가는 경우';
  const description = '이 설명은 카드의 두 줄 설명 자리를 넘어가므로 잘려야 합니다';
  expect(Array.from(clampCardText(title)).length).toBeLessThanOrEqual(CARD_TITLE_LIMIT);
  expect(Array.from(clampCardText(description, CARD_DESCRIPTION_LIMIT)).length)
    .toBeLessThanOrEqual(CARD_DESCRIPTION_LIMIT);
  expect(clampCardText('  짧은 이름  ')).toBe('짧은 이름');
});
