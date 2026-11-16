import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Switch } from './Switch';

afterEach(cleanup);

describe('Switch', () => {
  test('test_10a_switch_is_a_named_on_off_control', () => {
    render(<Switch label="자동 저장">자동 저장</Switch>);

    const control = screen.getByRole('switch', { name: '자동 저장' });
    expect(control.getAttribute('aria-checked')).toBe('false');
  });

  test('test_10a_switch_toggles_with_a_click', () => {
    render(<Switch label="자동 저장">자동 저장</Switch>);

    const control = screen.getByRole('switch', { name: '자동 저장' });
    fireEvent.click(control);

    expect(control.getAttribute('aria-checked')).toBe('true');
  });

  test('test_10a_switch_can_start_checked', () => {
    render(
      <Switch label="자동 저장" defaultChecked>
        자동 저장
      </Switch>,
    );

    expect(screen.getByRole('switch', { name: '자동 저장' }).getAttribute('aria-checked')).toBe(
      'true',
    );
  });
});
