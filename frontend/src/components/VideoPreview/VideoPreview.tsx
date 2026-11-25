import type { ReactNode } from 'react';
import { Film } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import { SentenceLines } from '../SentenceLines';

import './VideoPreview.css';

export type VideoPreviewState = 'empty' | 'loading' | 'ready';

export type VideoPreviewProps = {
  /** The accessible name of the ready placeholder when there is no custom media. */
  placeholderLabel?: string;
  state?: VideoPreviewState;
  /** The media or status content. Name custom media at its source. */
  children?: ReactNode;
  /** The empty or loading text that accompanies the default placeholder. */
  note?: string;
  /** The length chip on a ready preview. */
  duration?: string;
  className?: string;
};

/**
 * The 9:16 preview with the decided media radius. It is a picture, not a
 * control: the play row below owns playback. The placeholder, the loading mark
 * and the ready frame all keep the same box.
 */
export function VideoPreview({
  placeholderLabel,
  state = 'empty',
  children,
  note,
  duration,
  className,
}: VideoPreviewProps) {
  const readyLabel = state === 'ready' ? placeholderLabel : undefined;

  return (
    <div
      className={cn('video-preview', `video-preview--${state}`, className)}
      data-state={state}
    >
      {children ?? (
        <>
          {state === 'loading' ? (
            <span className="spinner" aria-hidden="true" />
          ) : (
            <Film
              className={
                state === 'ready'
                  ? 'video-preview__mark video-preview__mark--ready'
                  : 'video-preview__mark'
              }
              role={readyLabel === undefined ? undefined : 'img'}
              aria-label={readyLabel}
              aria-hidden={readyLabel === undefined || undefined}
            />
          )}
          {state !== 'ready' && note !== undefined ? (
            <span className="video-preview__note" role="status">
              <SentenceLines>{note}</SentenceLines>
            </span>
          ) : null}
        </>
      )}
      {duration === undefined ? null : <span className="video-preview__duration">{duration}</span>}
    </div>
  );
}
