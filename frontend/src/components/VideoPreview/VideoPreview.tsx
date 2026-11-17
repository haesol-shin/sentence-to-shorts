import type { ReactNode } from 'react';
import { Film } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './VideoPreview.css';

export type VideoPreviewState = 'empty' | 'loading' | 'ready';

export type VideoPreviewProps = {
  /** The accessible name of the picture. */
  label: string;
  state?: VideoPreviewState;
  /** The still picture. The fallbacks stay quiet and use tokens only. */
  children?: ReactNode;
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
  label,
  state = 'empty',
  children,
  duration,
  className,
}: VideoPreviewProps) {
  return (
    <div
      className={cn('video-preview', `video-preview--${state}`, className)}
      role="img"
      aria-label={label}
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
              aria-hidden="true"
            />
          )}
          {state === 'empty' || state === 'loading' ? (
            <span className="video-preview__note">
              {state === 'loading' ? '미리보기를 준비하는 중' : '장면 그림이 아직 없어요'}
            </span>
          ) : null}
        </>
      )}
      {duration === undefined ? null : <span className="video-preview__duration">{duration}</span>}
    </div>
  );
}
