import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Progress } from './Progress';

afterEach(cleanup);

describe('Progress', () => {
  test('test_10a_progress_announces_its_value_and_label', () => {
    render(<Progress value={40} label="장면 3개 만드는 중" />);

    const bar = screen.getByRole('progressbar', { name: '장면 3개 만드는 중' });
    expect(bar.getAttribute('aria-valuenow')).toBe('40');
    expect(screen.getByText('40%')).toBeTruthy();
  });

  test('test_10a_progress_without_a_value_is_indeterminate', () => {
    render(<Progress value={null} label="만드는 중" />);

    const bar = screen.getByRole('progressbar', { name: '만드는 중' });
    expect(bar.getAttribute('aria-valuenow')).toBeNull();
    expect(screen.getByText('진행 중')).toBeTruthy();
  });
});
