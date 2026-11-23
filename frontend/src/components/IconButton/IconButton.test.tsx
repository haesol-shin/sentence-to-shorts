import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, describe, expect, test } from 'vitest';

import { IconButton } from './IconButton';

afterEach(cleanup);

describe('IconButton', () => {
  test('test_10a_icon_button_has_an_accessible_name', () => {
    render(
      <IconButton label="설정">
        <span aria-hidden="true">+</span>
      </IconButton>,
    );

    expect(screen.getByRole('button', { name: '설정' })).toBeTruthy();
  });

  test('test_10a_icon_button_reports_selected_and_forwards_its_ref', () => {
    const ref = createRef<HTMLButtonElement>();
    render(
      <IconButton label="설정" selected ref={ref}>
        <span aria-hidden="true">+</span>
      </IconButton>,
    );

    const button = screen.getByRole('button', { name: '설정' });
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(ref.current).toBe(button);
  });

  test('test_10a_icon_button_forced_disabled_is_not_pressable', () => {
    render(
      <IconButton label="설정" forceState="disabled">
        <span aria-hidden="true">+</span>
      </IconButton>,
    );

    const button = screen.getByRole('button', { name: '설정' }) as HTMLButtonElement;
    fireEvent.click(button);
    expect(button.disabled).toBe(true);
  });

  test('test_w0_icon_button_compact_is_a_size_variant_and_the_default_stays_full_size', () => {
    render(
      <>
        <IconButton label="기본">
          <span aria-hidden="true">+</span>
        </IconButton>
        <IconButton label="보내기" size="compact">
          <span aria-hidden="true">+</span>
        </IconButton>
      </>,
    );

    expect(screen.getByRole('button', { name: '기본' }).className).toContain('icon-button--default');
    const compact = screen.getByRole('button', { name: '보내기' });
    expect(compact.className).toContain('icon-button--compact');
    // The 44 hit area comes from the shared ring, which the compact size keeps.
    expect(compact.className).toContain('hit-area');
  });
});
