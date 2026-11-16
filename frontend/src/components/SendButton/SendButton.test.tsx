import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { SendButton } from './SendButton';

afterEach(cleanup);

describe('SendButton', () => {
  test('test_10a_send_button_keeps_its_name_while_loading', () => {
    render(<SendButton label="보내기" loading />);

    const button = screen.getByRole('button', { name: '보내기' });
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.querySelector('.spinner')).not.toBeNull();
  });

  test('test_10a_send_button_disabled_is_not_pressed', () => {
    render(<SendButton label="보내기" disabled />);

    expect((screen.getByRole('button', { name: '보내기' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
