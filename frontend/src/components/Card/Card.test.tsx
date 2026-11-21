import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { Card } from './Card';

afterEach(cleanup);

describe('Card', () => {
  test('test_10a_card_reports_its_selected_state', () => {
    render(<Card variant="format" label="세로 영상" selected />);

    const card = screen.getByRole('button', { name: '세로 영상' });
    expect(card.getAttribute('aria-pressed')).toBe('true');
    expect(card.getAttribute('data-selected')).toBe('');
  });

  test('test_10a_scene_card_shows_its_number_and_duration', () => {
    render(
      <Card variant="scene" label="편의점 앞에서 시작해요" number={3} duration="약 3초" />,
    );

    const card = screen.getByRole('button', { name: '편의점 앞에서 시작해요' });
    expect(card.textContent).toContain('3');
    expect(card.textContent).toContain('약 3초');
  });

  test('test_10a_card_forced_disabled_does_not_run_its_action', () => {
    const onClick = vi.fn();
    render(<Card variant="scene" label="장면 1" forceState="disabled" onClick={onClick} />);

    const card = screen.getByRole('button', { name: '장면 1' });
    fireEvent.click(card);

    expect((card as HTMLButtonElement).disabled).toBe(true);
    expect(onClick).not.toHaveBeenCalled();
  });

  test('test_10a_card_busy_shows_the_work_status_and_stays_pressable', () => {
    const onClick = vi.fn();
    render(<Card variant="scene" label="편의점 앞" busy busyLabel="Fixing" onClick={onClick} />);

    const card = screen.getByRole('button', { name: '편의점 앞' });
    expect(card.hasAttribute('data-busy')).toBe(true);
    expect(screen.getByRole('status').textContent).toContain('Fixing');
    expect(card.querySelector('.spinner')).not.toBeNull();
    expect(card.querySelector('.card__band')).not.toBeNull();

    fireEvent.click(card);

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
