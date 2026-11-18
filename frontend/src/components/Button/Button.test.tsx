import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { Button } from './Button';

afterEach(cleanup);

describe('Button', () => {
  test('test_10a_button_forwards_its_ref_to_the_dom_button', () => {
    const ref = createRef<HTMLButtonElement>();
    render(<Button ref={ref}>저장</Button>);

    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
    expect(ref.current?.type).toBe('button');
  });

  test('test_10a_button_running_becomes_the_stop_control', () => {
    const onStop = vi.fn();
    const onClick = vi.fn();
    render(
      <Button running stopLabel="멈추기" onStop={onStop} onClick={onClick}>
        AI로 다시 쓰기
      </Button>,
    );

    const button = screen.getByRole('button', { name: '멈추기' });
    expect(button.textContent).toContain('■');
    expect(button.querySelector('.spinner')).toBeNull();
    expect(button.hasAttribute('data-running')).toBe(true);

    fireEvent.click(button);

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onClick).not.toHaveBeenCalled();
  });

  test('test_10a_button_forced_disabled_does_not_run_its_action', () => {
    const onClick = vi.fn();
    render(
      <Button forceState="disabled" onClick={onClick}>
        저장
      </Button>,
    );

    const button = screen.getByRole('button', { name: '저장' });
    fireEvent.click(button);

    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(onClick).not.toHaveBeenCalled();
  });

  test('test_10a_button_click_reaches_the_caller', () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>저장</Button>);

    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
