import { cleanup, render, screen } from '@testing-library/react';
import { AlertCircle } from 'lucide-react';
import { afterEach, describe, expect, test } from 'vitest';

import { EmptyState } from './EmptyState';

afterEach(cleanup);

describe('EmptyState', () => {
  test('test_10a_empty_state_names_the_next_action', () => {
    render(
      <EmptyState title="아직 만든 영상이 없어요" actions={<button type="button">새 영상</button>}>
        문장 하나로 첫 영상을 만들 수 있어요.
      </EmptyState>,
    );

    expect(screen.getByRole('heading', { name: '아직 만든 영상이 없어요' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '새 영상' })).toBeTruthy();
  });

  test('test_10a_error_state_is_announced_as_an_alert', () => {
    render(
      <EmptyState
        tone="error"
        icon={<AlertCircle />}
        title="영상을 만들지 못했어요"
        actions={<button type="button">다시 시도</button>}
      >
        연결을 확인한 뒤 다시 시도해 주세요.
      </EmptyState>,
    );

    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy();
  });
});
