import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Settings } from 'lucide-react';
import { createRef } from 'react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { SidebarItem } from './SidebarItem';

afterEach(cleanup);

describe('SidebarItem', () => {
  test('test_10a_sidebar_item_forwards_its_ref_and_keeps_its_name', () => {
    const ref = createRef<HTMLButtonElement>();
    render(
      <SidebarItem ref={ref} label="설정">
        <Settings />
      </SidebarItem>,
    );

    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
    expect(screen.getByRole('button', { name: '설정' })).toBe(ref.current);
  });

  test('test_10a_sidebar_item_marks_the_current_page', () => {
    render(
      <SidebarItem label="내 영상" selected>
        <Settings />
      </SidebarItem>,
    );

    expect(screen.getByRole('button', { name: '내 영상' }).getAttribute('aria-current')).toBe('page');
  });

  test('test_10a_sidebar_item_forced_disabled_does_not_run_its_action', () => {
    const onClick = vi.fn();
    render(
      <SidebarItem label="설정" forceState="disabled" onClick={onClick}>
        <Settings />
      </SidebarItem>,
    );

    const button = screen.getByRole('button', { name: '설정' });
    fireEvent.click(button);

    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(onClick).not.toHaveBeenCalled();
  });
});
