import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { ReorderList } from './ReorderList';

const LABELS = {
  grip: (item: string) => `Reorder: ${item}`,
  up: (item: string) => `Move up: ${item}`,
  down: (item: string) => `Move down: ${item}`,
};

const ITEMS = [
  { id: 'scene-1', label: '첫 장면' },
  { id: 'scene-2', label: '둘째 장면' },
  { id: 'scene-3', label: '셋째 장면' },
];

afterEach(cleanup);

describe('ReorderList', () => {
  test('test_10a_reorder_list_moves_a_row_down_with_its_control', () => {
    const onReorder = vi.fn();
    render(<ReorderList label="장면 순서" labels={LABELS} items={ITEMS} onReorder={onReorder} />);

    fireEvent.click(screen.getByRole('button', { name: 'Move down: 첫 장면' }));

    expect(onReorder).toHaveBeenCalledWith([
      { id: 'scene-2', label: '둘째 장면' },
      { id: 'scene-1', label: '첫 장면' },
      { id: 'scene-3', label: '셋째 장면' },
    ]);
  });

  test('test_10a_reorder_list_disables_the_move_that_leaves_the_list', () => {
    render(<ReorderList label="장면 순서" labels={LABELS} items={ITEMS} />);

    expect(
      (screen.getByRole('button', { name: 'Move up: 첫 장면' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole('button', { name: 'Move down: 셋째 장면' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  test('test_10a_reorder_list_names_every_grip', () => {
    render(<ReorderList label="장면 순서" labels={LABELS} items={ITEMS} />);

    for (const item of ITEMS) {
      expect(screen.getByRole('button', { name: `Reorder: ${item.label}` })).toBeTruthy();
    }
  });
});
