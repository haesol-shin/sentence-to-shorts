import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { PlaybackControls } from './PlaybackControls';

afterEach(cleanup);

const LABELS = { play: 'Play', pause: 'Pause', seek: 'Playback position', mute: 'Mute', unmute: 'Unmute' };

describe('PlaybackControls', () => {
  test('test_10a_playback_controls_toggle_play_and_sound', () => {
    const onToggle = vi.fn();
    const onToggleMute = vi.fn();
    render(
      <PlaybackControls label="Playback controls" labels={LABELS} onToggle={onToggle} onToggleMute={onToggleMute} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    fireEvent.click(screen.getByRole('button', { name: 'Mute' }));

    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onToggleMute).toHaveBeenCalledTimes(1);
  });

  test('test_10a_playback_controls_show_the_pause_state_without_moving', () => {
    render(<PlaybackControls label="Playback controls" labels={LABELS} playing muted />);

    expect(screen.getByRole('button', { name: 'Pause' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Unmute' })).toBeTruthy();
  });

  test('test_10a_playback_controls_seek_reaches_the_caller', () => {
    const onSeek = vi.fn();
    render(<PlaybackControls label="Playback controls" labels={LABELS} position={20} onSeek={onSeek} />);

    fireEvent.change(screen.getByRole('slider', { name: 'Playback position' }), {
      target: { value: '40' },
    });

    expect(onSeek).toHaveBeenCalledWith(40);
  });

  test('test_10a_playback_controls_forced_disabled_stops_both_controls', () => {
    render(<PlaybackControls label="Playback controls" labels={LABELS} forceState="disabled" />);

    expect((screen.getByRole('button', { name: 'Play' }) as HTMLButtonElement).disabled).toBe(true);
    expect(
      (screen.getByRole('button', { name: 'Mute' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
