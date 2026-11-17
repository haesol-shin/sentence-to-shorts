import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { VideoPreview } from './VideoPreview';

afterEach(cleanup);

describe('VideoPreview', () => {
  test('test_10a_video_preview_is_a_named_picture', () => {
    render(<VideoPreview label="장면 1 미리보기" />);

    const preview = screen.getByRole('img', { name: '장면 1 미리보기' });
    expect(preview.getAttribute('data-state')).toBe('empty');
    expect(preview.textContent).toContain('장면 그림이 아직 없어요');
  });

  test('test_10a_video_preview_keeps_the_same_surface_while_loading', () => {
    render(<VideoPreview label="장면 1 미리보기" state="loading" />);

    const preview = screen.getByRole('img', { name: '장면 1 미리보기' });
    expect(preview.querySelector('.spinner')).not.toBeNull();
    expect(preview.textContent).toContain('미리보기를 준비하는 중');
  });

  test('test_10a_video_preview_shows_the_length_on_a_ready_frame', () => {
    render(<VideoPreview label="완성된 영상" state="ready" duration="0:07" />);

    expect(screen.getByRole('img', { name: '완성된 영상' }).textContent).toContain('0:07');
  });
});
