import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Toast } from './Toast';

afterEach(cleanup);

describe('Toast', () => {
  test('test_10a_toast_announces_one_confirmation', async () => {
    render(<Toast open>대본을 저장했어요</Toast>);

    const toast = screen.getByRole('status');
    expect(toast.textContent).toBe('대본을 저장했어요');
    expect(toast.getAttribute('aria-live')).toBe('polite');
    expect(toast.getAttribute('data-state')).toBe('closed');
    await waitFor(() => expect(toast.getAttribute('data-state')).toBe('open'));
  });

  test('test_10a_toast_is_absent_while_closed', () => {
    render(<Toast open={false}>대본을 저장했어요</Toast>);

    expect(screen.queryByRole('status')).toBeNull();
  });
});
