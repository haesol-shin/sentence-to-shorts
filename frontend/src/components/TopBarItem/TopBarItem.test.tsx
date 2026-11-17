import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { TopBarItem } from './TopBarItem';

afterEach(cleanup);

describe('TopBarItem', () => {
  test('test_10a_top_bar_item_forwards_its_ref_for_popup_triggers', () => {
    const ref = createRef<HTMLButtonElement>();
    render(<TopBarItem ref={ref} label="영상 설정" />);

    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
    expect(ref.current?.getAttribute('aria-expanded')).toBeNull();
  });

  test('test_10a_top_bar_item_reserves_the_bold_width_in_every_state', () => {
    render(<TopBarItem label="영상 설정" forceState="open" />);

    const item = screen.getByRole('button', { name: '영상 설정' });
    expect(item.getAttribute('data-force-state')).toBe('open');
    expect(item.querySelectorAll('.label-box__text')).toHaveLength(3);
  });

  test('test_10a_top_bar_item_click_reaches_the_caller', () => {
    const onClick = vi.fn();
    render(<TopBarItem label="영상 설정" onClick={onClick} />);

    fireEvent.click(screen.getByRole('button', { name: '영상 설정' }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
