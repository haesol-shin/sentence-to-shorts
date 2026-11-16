import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Chip } from './Chip';
import { CloseButton } from '../CloseButton/CloseButton';

afterEach(cleanup);

describe('Chip', () => {
  test('test_10a_chip_shows_loading_with_a_progress_mark', () => {
    render(
      <Chip state="loading" remove={<CloseButton label="파일 지우기" size="sm" />}>
        대본.md
      </Chip>,
    );

    const chip = screen.getByText('대본.md').closest('.chip');
    expect(chip?.getAttribute('data-state')).toBe('loading');
    expect(chip?.querySelector('.spinner')).not.toBeNull();
  });

  test('test_10a_chip_error_uses_the_error_state_and_keeps_its_remove_control', () => {
    render(
      <Chip state="error" remove={<CloseButton label="파일 지우기" size="sm" />}>
        참고영상.mp4
      </Chip>,
    );

    const chip = screen.getByText('참고영상.mp4').closest('.chip');
    expect(chip?.getAttribute('data-state')).toBe('error');
    expect(screen.getByRole('button', { name: '파일 지우기' })).toBeTruthy();
  });

  test('test_10a_chip_marks_a_forced_focus_state', () => {
    render(<Chip forceState="focus-visible">대본.md</Chip>);

    expect(screen.getByText('대본.md').closest('.chip')?.getAttribute('data-force-state')).toBe(
      'focus-visible',
    );
  });
});
