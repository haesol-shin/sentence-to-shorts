import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { CloseButton } from './CloseButton';

afterEach(cleanup);

describe('CloseButton', () => {
  test('test_10a_close_button_has_one_name_for_every_size', () => {
    render(
      <>
        <CloseButton label="창 닫기" size="md" />
        <CloseButton label="파일 지우기" size="sm" />
      </>,
    );

    const large = screen.getByRole('button', { name: '창 닫기' });
    const small = screen.getByRole('button', { name: '파일 지우기' });
    expect(large.classList.contains('close-button--md')).toBe(true);
    expect(small.classList.contains('close-button--sm')).toBe(true);
    expect(small.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
  });

  test('test_10a_close_button_runs_the_remove_action', () => {
    const onRemove = vi.fn();
    render(<CloseButton label="파일 지우기" size="sm" onClick={onRemove} />);

    fireEvent.click(screen.getByRole('button', { name: '파일 지우기' }));

    expect(onRemove).toHaveBeenCalledTimes(1);
  });
});
