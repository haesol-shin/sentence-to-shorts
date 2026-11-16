import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { RangeDialog } from './RangeDialog';

afterEach(cleanup);

const CHANGES = [
  { label: '분위기', before: '차분함', after: '유쾌함' },
  { label: '장면 수', before: '4개', after: '5개' },
];

describe('RangeDialog', () => {
  test('test_10a_range_dialog_shows_every_change_and_the_rebuild_scope', () => {
    render(
      <RangeDialog
        defaultOpen
        intro="여러 장면이 바뀌어서 적용 전에 확인해요."
        changes={CHANGES}
        scope={['대본 다시 쓰기', '장면 1, 2의 목소리와 렌더']}
        confirmLabel="적용"
      />,
    );

    expect(screen.getByRole('alertdialog', { name: '다시 만들 범위를 확인해 주세요' })).toBeTruthy();
    expect(screen.getByText('분위기')).toBeTruthy();
    expect(screen.getByText('유쾌함')).toBeTruthy();
    expect(screen.getByText('장면 1, 2의 목소리와 렌더')).toBeTruthy();
  });
});
