import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { Button } from '../Button/Button';
import { ConfirmDialog } from './ConfirmDialog';

afterEach(cleanup);

describe('ConfirmDialog', () => {
  test('test_10a_confirm_dialog_is_an_alert_with_cancel_first', () => {
    render(
      <ConfirmDialog
        defaultOpen
        title="파일을 지울까요?"
        confirmLabel="지우기"
        onConfirm={() => undefined}
      >
        지운 파일은 되돌릴 수 없어요.
      </ConfirmDialog>,
    );

    const dialog = screen.getByRole('alertdialog', { name: '파일을 지울까요?' });
    const buttons = [...dialog.querySelectorAll('button')].map((button) => button.textContent);
    expect(buttons).toEqual(['취소', '지우기']);
    expect(screen.getByText('지운 파일은 되돌릴 수 없어요.')).toBeTruthy();
  });

  test('test_10a_confirm_dialog_runs_the_action_and_closes', async () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="파일을 지울까요?"
        confirmLabel="지우기"
        cancelLabel={null}
        onConfirm={onConfirm}
        trigger={<Button>지우기</Button>}
      >
        지운 파일은 되돌릴 수 없어요.
      </ConfirmDialog>,
    );

    fireEvent.click(screen.getByRole('button', { name: '지우기' }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '지우기' }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
