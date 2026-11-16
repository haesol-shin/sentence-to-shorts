import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { RadioGroup } from './RadioGroup';

afterEach(cleanup);

const OPTIONS = [
  { value: 'vertical', label: '세로' },
  { value: 'square', label: '정사각' },
  { value: 'wide', label: '가로' },
];

describe('RadioGroup', () => {
  test('test_10a_radio_group_names_the_group_and_marks_one_choice', () => {
    render(<RadioGroup label="화면 비율" options={OPTIONS} defaultValue="vertical" />);

    expect(screen.getByRole('radiogroup', { name: '화면 비율' })).toBeTruthy();
    expect(screen.getAllByRole('radio')).toHaveLength(3);
    expect(screen.getByRole('radio', { name: '세로' }).getAttribute('aria-checked')).toBe('true');
  });

  test('test_10a_radio_group_changes_with_a_click', () => {
    const onValueChange = vi.fn();
    render(
      <RadioGroup
        label="화면 비율"
        options={OPTIONS}
        defaultValue="vertical"
        onValueChange={onValueChange}
      />,
    );

    fireEvent.click(screen.getByRole('radio', { name: '가로' }));

    expect(onValueChange).toHaveBeenCalledWith('wide');
    expect(screen.getByRole('radio', { name: '가로' }).getAttribute('aria-checked')).toBe('true');
  });
});
