import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { StageIndicator } from './StageIndicator';

const STAGES = [
  { value: 'concept', label: '컨셉' },
  { value: 'script', label: '대본' },
  { value: 'edit', label: '편집' },
  { value: 'export', label: '내보내기' },
];

afterEach(cleanup);

describe('StageIndicator', () => {
  test('test_10a_stage_indicator_marks_only_the_current_stage', () => {
    render(<StageIndicator label="단계" stages={STAGES} current="edit" />);

    const current = document.querySelector('[aria-current="step"]');
    expect(current?.textContent).toContain('편집');
    expect(screen.getByRole('button', { name: '컨셉' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '대본' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '내보내기' })).toBeNull();
  });

  test('test_10a_stage_indicator_moves_back_from_a_past_stage', () => {
    const onSelect = vi.fn();
    render(<StageIndicator label="단계" stages={STAGES} current="edit" onSelect={onSelect} />);

    fireEvent.click(screen.getByRole('button', { name: '대본' }));

    expect(onSelect).toHaveBeenCalledWith('script');
  });

  test('test_10a_stage_indicator_keeps_upcoming_stages_unpressable', () => {
    render(<StageIndicator label="단계" stages={STAGES} current="concept" />);

    expect(screen.queryByRole('button')).toBeNull();
    expect(document.querySelector('.stage-indicator__step--upcoming')?.textContent).toContain('대본');
  });
});
