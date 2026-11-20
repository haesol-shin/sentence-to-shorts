import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { SendButton } from './SendButton';

afterEach(cleanup);

describe('SendButton', () => {
  test('test_10a_send_button_loading_names_the_stop_action', () => {
    const onClick = vi.fn();
    render(<SendButton label="Send" stopLabel="Stop the request" loading onClick={onClick} />);

    const button = screen.getByRole('button', { name: 'Stop the request' });
    expect(button.textContent).toContain('■');
    expect(button.querySelector('.spinner')).toBeNull();
    expect((button as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(button);

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  test('test_10a_send_button_disabled_is_not_pressed', () => {
    render(<SendButton label="Send" stopLabel="Stop the request" disabled />);

    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
