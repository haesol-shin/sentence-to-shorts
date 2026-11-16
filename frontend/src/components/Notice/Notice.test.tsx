import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Notice } from './Notice';

afterEach(cleanup);

describe('Notice', () => {
  test('test_10a_notice_error_is_an_alert_with_a_title_and_a_body', () => {
    render(
      <Notice tone="error" title="링크를 받지 못했어요">
        링크가 공개 상태인지 확인해 주세요.
      </Notice>,
    );

    const alert = screen.getByRole('alert');
    expect(alert.getAttribute('data-tone')).toBe('error');
    expect(alert.textContent).toContain('링크를 받지 못했어요');
    expect(alert.textContent).toContain('링크가 공개 상태인지 확인해 주세요.');
  });

  test('test_10a_notice_neutral_is_a_status', () => {
    render(<Notice>이 영상에서만 쓰는 값이에요.</Notice>);

    expect(screen.getByRole('status').textContent).toContain('이 영상에서만 쓰는 값이에요.');
  });
});
