import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { Button } from '../Button/Button';
import { Dialog, DialogClose } from './Dialog';

afterEach(cleanup);

describe('Dialog', () => {
  test('test_10a_dialog_opens_from_its_trigger_and_reports_the_state', async () => {
    render(
      <Dialog
        title="이 영상을 만들까요?"
        description="만들면 편집 화면으로 넘어가요."
        trigger={<Button>영상 만들기</Button>}
        actions={
          <DialogClose render={<Button variant="secondary">취소</Button>} />
        }
      />,
    );

    const trigger = screen.getByRole('button', { name: '영상 만들기' });
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(trigger);

    expect(await screen.findByRole('dialog', { name: '이 영상을 만들까요?' })).toBeTruthy();
    await waitFor(() => expect(trigger.getAttribute('aria-expanded')).toBe('true'));
  });

  test('test_10a_alert_window_uses_the_alert_role', () => {
    render(
      <Dialog
        variant="alert"
        defaultOpen
        title="저장하지 못했어요"
        description="연결을 확인하고 다시 시도해 주세요."
      />,
    );

    expect(screen.getByRole('alertdialog', { name: '저장하지 못했어요' })).toBeTruthy();
  });

  test('test_10a_dialog_takes_its_name_from_a_visible_outside_title', async () => {
    render(
      <Dialog defaultOpen labelledBy="outside-dialog-title">
        <h2 id="outside-dialog-title">바깥 제목</h2>
      </Dialog>,
    );

    expect(await screen.findByRole('dialog', { name: '바깥 제목' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '바깥 제목' })).toBeTruthy();
    expect(screen.queryByRole('heading', { level: 2, name: '' })).toBeNull();
  });

  test('test_10a_dialog_close_control_returns_focus_to_the_trigger', async () => {
    render(
      <Dialog
        title="파일을 지울까요?"
        trigger={<Button>지우기</Button>}
        actions={<DialogClose render={<Button variant="secondary">취소</Button>} />}
      />,
    );

    const trigger = screen.getByRole('button', { name: '지우기' });
    fireEvent.click(trigger);
    fireEvent.click(await screen.findByRole('button', { name: '취소' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(trigger).toBe(document.activeElement));
  });
});
