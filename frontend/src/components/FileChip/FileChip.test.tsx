import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { FileChip } from './FileChip';

afterEach(cleanup);

describe('FileChip', () => {
  test('test_10a_file_chip_shows_the_name_kind_and_length', () => {
    render(<FileChip name="대본_최종.md" detail="글 · 12KB" />);

    expect(screen.getByText('대본_최종.md')).toBeTruthy();
    expect(screen.getByText('글 · 12KB')).toBeTruthy();
  });

  test('test_10a_file_chip_error_keeps_the_sentence_and_the_retry', () => {
    const { container } = render(
      <FileChip
        name="참고_영상.mp4"
        detail="올리지 못했어요. 다시 시도해 주세요."
        state="error"
        retry={<button type="button">다시</button>}
        remove={<button type="button">파일 지우기</button>}
      />,
    );

    expect(container.querySelector('.file-chip')?.getAttribute('data-state')).toBe('error');
    expect(screen.getByRole('button', { name: '다시' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '파일 지우기' })).toBeTruthy();
  });

  test('test_10a_file_chip_loading_shows_progress_without_a_number', () => {
    const { container } = render(<FileChip name="BGM.mp3" state="loading" progress={0.4} />);

    const chip = container.querySelector<HTMLElement>('.file-chip');
    expect(chip?.style.getPropertyValue('--file-progress')).toBe('40%');
    expect(container.querySelector('.file-chip__bar-fill')).not.toBeNull();
  });

  test('test_w0_file_chip_loading_exposes_the_progress_to_assistive_technology', () => {
    render(<FileChip name="BGM.mp3" state="loading" progress={0.45} />);

    const bar = screen.getByRole('progressbar', { name: 'BGM.mp3' });
    expect(bar.getAttribute('aria-valuenow')).toBe('45');
    cleanup();
    render(<FileChip name="BGM.mp3" detail="BGM" />);
    expect(screen.queryByRole('progressbar')).toBeNull();
  });
});
