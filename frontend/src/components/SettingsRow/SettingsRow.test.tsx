import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { SettingsRow } from './SettingsRow';

afterEach(cleanup);

describe('SettingsRow', () => {
  test('test_10a_settings_row_puts_the_control_next_to_its_label', () => {
    render(
      <SettingsRow
        label="자동 저장"
        description="편집하는 동안 바뀐 값을 저장해요."
        control={<button type="button">켜짐</button>}
      />,
    );

    expect(screen.getByText('자동 저장')).toBeTruthy();
    expect(screen.getByText('편집하는 동안 바뀐 값을 저장해요.')).toBeTruthy();
    expect(screen.getByRole('button', { name: '켜짐' })).toBeTruthy();
  });

  test('test_10a_settings_row_can_carry_a_visible_reason', () => {
    render(
      <SettingsRow
        label="배경 음악"
        control={<button type="button">꺼짐</button>}
        note={<span>다음 단계에서 열려요.</span>}
      />,
    );

    expect(screen.getByText('다음 단계에서 열려요.')).toBeTruthy();
  });
});
