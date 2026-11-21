import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { Composer } from './Composer';

afterEach(cleanup);

describe('Composer', () => {
  test('test_10a_composer_names_the_field_and_reports_typed_text', () => {
    const onValueChange = vi.fn();
    render(
      <Composer label="메시지 입력" sendLabel="Send" stopLabel="Stop" placeholder="어떤 영상을 만들까요?" onValueChange={onValueChange} />,
    );

    const field = screen.getByRole('textbox', { name: '메시지 입력' });
    fireEvent.change(field, { target: { value: '차분한 다큐멘터리로' } });

    expect((field as HTMLTextAreaElement).value).toBe('차분한 다큐멘터리로');
    expect(onValueChange).toHaveBeenCalledWith('차분한 다큐멘터리로');
  });

  test('test_10a_composer_sends_with_a_named_button', () => {
    const onSend = vi.fn();
    render(<Composer label="메시지 입력" sendLabel="Send" stopLabel="Stop" defaultValue="보내 주세요" onSend={onSend} />);

    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(onSend).toHaveBeenCalledTimes(1);
  });

  test('test_10a_composer_keeps_the_send_button_while_loading', () => {
    const onSend = vi.fn();
    render(<Composer label="Message" sendLabel="Send" stopLabel="Stop the request" loading onSend={onSend} />);

    const send = screen.getByRole('button', { name: 'Stop the request' });
    expect((send as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(send);

    expect(onSend).toHaveBeenCalledTimes(1);
  });

  test('test_10a_composer_marks_the_file_drop_state', () => {
    const { container } = render(
      <Composer label="메시지 입력" sendLabel="Send" stopLabel="Stop" dropActive placeholder="여기에 놓으면 올라가요" />,
    );

    expect(container.querySelector('.composer')?.hasAttribute('data-drop')).toBe(true);
    expect(screen.getByPlaceholderText('여기에 놓으면 올라가요')).toBeTruthy();
  });

  test('test_10a_composer_disabled_turns_off_its_controls', () => {
    render(<Composer label="메시지 입력" sendLabel="Send" stopLabel="Stop" disabled attachLabel="파일 넣기" />);

    expect((screen.getByRole('textbox', { name: '메시지 입력' }) as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '파일 넣기' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
