import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { Tabs } from './Tabs';

afterEach(cleanup);

const ITEMS = [
  { value: 'script', label: '대본' },
  { value: 'caption', label: '자막' },
  { value: 'voice', label: '목소리' },
];

describe('Tabs', () => {
  test('test_10a_tabs_expose_one_named_tab_list_and_the_selected_tab', () => {
    render(<Tabs label="영상 값" items={ITEMS} defaultValue="script" />);

    expect(screen.getByRole('tablist', { name: '영상 값' })).toBeTruthy();
    expect(screen.getAllByRole('tab')).toHaveLength(3);
    expect(screen.getByRole('tab', { name: '대본' }).getAttribute('aria-selected')).toBe('true');
  });

  test('test_10a_tabs_change_with_a_click_and_report_the_value', () => {
    const onValueChange = vi.fn();
    render(<Tabs label="영상 값" items={ITEMS} defaultValue="script" onValueChange={onValueChange} />);

    fireEvent.click(screen.getByRole('tab', { name: '자막' }));

    expect(onValueChange).toHaveBeenCalledWith('caption');
    expect(screen.getByRole('tab', { name: '자막' }).getAttribute('aria-selected')).toBe('true');
  });

  test('test_10a_tabs_show_a_disabled_tab_as_disabled', () => {
    render(
      <Tabs
        label="영상 값"
        items={[ITEMS[0], { ...ITEMS[1], disabled: true }, ITEMS[2]]}
        defaultValue="script"
      />,
    );

    const tab = screen.getByRole('tab', { name: '자막' });
    expect(tab.getAttribute('aria-disabled')).toBe('true');
  });
});
