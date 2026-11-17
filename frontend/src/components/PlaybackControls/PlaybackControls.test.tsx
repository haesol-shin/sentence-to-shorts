import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { PlaybackControls } from './PlaybackControls';

afterEach(cleanup);

describe('PlaybackControls', () => {
  test('test_10a_playback_controls_toggle_play_and_sound', () => {
    const onToggle = vi.fn();
    const onToggleMute = vi.fn();
    render(
      <PlaybackControls label="재생 조절" onToggle={onToggle} onToggleMute={onToggleMute} />,
    );

    fireEvent.click(screen.getByRole('button', { name: '재생' }));
    fireEvent.click(screen.getByRole('button', { name: '소리 끄기' }));

    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onToggleMute).toHaveBeenCalledTimes(1);
  });

  test('test_10a_playback_controls_show_the_pause_state_without_moving', () => {
    render(<PlaybackControls label="재생 조절" playing muted />);

    expect(screen.getByRole('button', { name: '일시정지' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '소리 켜기' })).toBeTruthy();
  });

  test('test_10a_playback_controls_seek_reaches_the_caller', () => {
    const onSeek = vi.fn();
    render(<PlaybackControls label="재생 조절" position={20} onSeek={onSeek} />);

    fireEvent.change(screen.getByRole('slider', { name: '재생 위치' }), {
      target: { value: '40' },
    });

    expect(onSeek).toHaveBeenCalledWith(40);
  });

  test('test_10a_playback_controls_forced_disabled_stops_both_controls', () => {
    render(<PlaybackControls label="재생 조절" forceState="disabled" />);

    expect((screen.getByRole('button', { name: '재생' }) as HTMLButtonElement).disabled).toBe(true);
    expect(
      (screen.getByRole('button', { name: '소리 끄기' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
