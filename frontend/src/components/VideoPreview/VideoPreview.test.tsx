import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { VideoPreview } from './VideoPreview';

afterEach(cleanup);

describe('VideoPreview', () => {
  test('test_10a_video_preview_exposes_empty_and_loading_notes_as_status', () => {
    const { rerender } = render(<VideoPreview note="장면 그림이 아직 없어요" />);

    expect(screen.getByRole('status').textContent).toBe('장면 그림이 아직 없어요');
    expect(screen.queryByRole('img')).toBeNull();

    rerender(<VideoPreview state="loading" note="미리보기를 준비하는 중" />);

    expect(screen.getByRole('status').textContent).toBe('미리보기를 준비하는 중');
    expect(screen.queryByRole('img')).toBeNull();
  });

  test('test_10a_video_preview_exposes_the_length_separately_from_its_picture', () => {
    render(<VideoPreview placeholderLabel="영상 미리보기" state="ready" duration="0:07" />);

    const picture = screen.getByRole('img', { name: '영상 미리보기' });
    expect(picture.contains(screen.getByText('0:07'))).toBe(false);
  });
});
