import type { CSSProperties } from 'react';
import { Pause, Play, Volume2, VolumeX } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './PlaybackControls.css';

import { statesOf, type ForceState } from '../force-state';

export type PlaybackControlsProps = {
  /** The accessible name of the row. */
  label: string;
  /** Accessible names for the visual-only controls. */
  labels: {
    play: string;
    pause: string;
    seek: string;
    mute: string;
    unmute: string;
  };
  playing?: boolean;
  onToggle?: () => void;
  /** The played share, 0 to 100. */
  position?: number;
  onSeek?: (position: number) => void;
  /** For example "0:00". */
  current?: string;
  /** For example "약 0:07". */
  duration?: string;
  muted?: boolean;
  onToggleMute?: () => void;
  disabled?: boolean;
  /** Forces the play and mute control state for the gallery. */
  forceState?: ForceState;
  /** Shows that forced state on the play control or the sound control. */
  forceControl?: 'play' | 'sound';
  /** Forces the progress state for the gallery. */
  forceProgressState?: ForceState;
  className?: string;
};

/**
 * The play row under the preview. The play and sound controls keep the same
 * 40px box and fill 44 with the shared ring. The seek bar is a 44 high range
 * control whose track is the approved 6px bar; the thumb stays invisible so
 * the row looks the same from play to pause.
 */
export function PlaybackControls({
  label,
  labels,
  playing = false,
  onToggle,
  position = 0,
  onSeek,
  current = '0:00',
  duration = '약 0:07',
  muted = false,
  onToggleMute,
  disabled = false,
  forceState,
  forceControl = 'play',
  forceProgressState,
  className,
}: PlaybackControlsProps) {
  const forced = statesOf(forceState);
  const progressForced = statesOf(forceProgressState);
  const isDisabled = disabled || forced.includes('disabled');
  const playForced = forceControl === 'play' ? forced : [];
  const soundForced = forceControl === 'sound' ? forced : [];
  const style = { '--player-progress': `${Math.max(0, Math.min(100, position))}%` } as CSSProperties;

  return (
    <div className={cn('player', className)} role="group" aria-label={label}>
      <button
        type="button"
        className="player__control hit-area focus-ring"
        aria-label={playing ? labels.pause : labels.play}
        data-force-state={playForced.length > 0 ? playForced.join(' ') : undefined}
        disabled={isDisabled}
        onClick={onToggle}
      >
        {playing ? (
          <Pause aria-hidden="true" fill="currentColor" className="pause-glyph" />
        ) : (
          <Play aria-hidden="true" fill="currentColor" className="play-glyph" />
        )}
      </button>
      <span className="player__seek" style={style} data-disabled={isDisabled ? '' : undefined}>
        <span className="player__track" aria-hidden="true">
          <span className="player__fill" />
        </span>
        <input
          className="player__progress focus-ring focus-ring--inset"
          type="range"
          min={0}
          max={100}
          step={1}
          value={Math.max(0, Math.min(100, position))}
          aria-label={labels.seek}
          data-force-state={progressForced.length > 0 ? progressForced.join(' ') : undefined}
          disabled={isDisabled}
          onChange={(event) => onSeek?.(Number(event.target.value))}
        />
      </span>
      <span className="player__time">
        {current} / {duration}
      </span>
      <button
        type="button"
        className="player__control hit-area focus-ring"
        aria-label={muted ? labels.unmute : labels.mute}
        data-force-state={soundForced.length > 0 ? soundForced.join(' ') : undefined}
        disabled={isDisabled}
        onClick={onToggleMute}
      >
        {muted ? <VolumeX aria-hidden="true" /> : <Volume2 aria-hidden="true" />}
      </button>
    </div>
  );
}
