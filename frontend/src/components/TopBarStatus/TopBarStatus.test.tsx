import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { TopBarStatus } from './TopBarStatus';

afterEach(cleanup);

describe('TopBarStatus', () => {
  test('test_10a_top_bar_status_opens_its_panel_with_a_name', async () => {
    render(
      <TopBarStatus
        label="저장 실패"
        tone="error"
        title="저장하지 못했어요"
        description="연결이 끊겨 저장하지 못했어요."
      />,
    );

    const trigger = screen.getByRole('button', { name: '저장 실패' });
    expect(trigger.getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(trigger);

    const panel = await screen.findByRole('dialog', { name: '저장하지 못했어요' });
    expect(panel).toBeTruthy();
    await waitFor(() => expect(trigger.getAttribute('aria-expanded')).toBe('true'));
  });

  test('test_10a_top_bar_status_closes_with_escape_and_returns_focus', async () => {
    render(
      <TopBarStatus
        label="저장 실패"
        tone="error"
        title="저장하지 못했어요"
        description="연결이 끊겨 저장하지 못했어요."
      />,
    );

    const trigger = screen.getByRole('button', { name: '저장 실패' });
    fireEvent.click(trigger);
    await screen.findByRole('dialog', { name: '저장하지 못했어요' });

    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(trigger).toBe(document.activeElement);
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
  });

  test('test_10a_top_bar_status_forced_state_does_not_open_the_panel', () => {
    const onOpenChange = vi.fn();
    render(
      <TopBarStatus
        label="저장 실패"
        title="저장하지 못했어요"
        description="연결이 끊겨 저장하지 못했어요."
        forceState="hover"
        onOpenChange={onOpenChange}
      />,
    );

    expect(screen.getByRole('button', { name: '저장 실패' }).getAttribute('data-force-state')).toBe(
      'hover',
    );
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});
