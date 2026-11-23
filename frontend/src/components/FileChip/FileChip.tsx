import type { CSSProperties, ReactNode } from 'react';
import { AlertCircle, FileText } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './FileChip.css';

import { statesOf, type ForceState } from '../force-state';

export type FileChipState = 'default' | 'loading' | 'error';

export type FileChipProps = {
  /** The file name, the one strong line. */
  name: string;
  /** The kind and length line, for example "영상 · 0:12". */
  detail?: ReactNode;
  state?: FileChipState;
  /** The upload progress from 0 to 1. Shown only while loading. */
  progress?: number;
  /** A small picture or file-kind mark. A file icon is the default. */
  lead?: ReactNode;
  /** The remove control. The caller composes a CloseButton so one part owns its size. */
  remove?: ReactNode;
  /** A retry control for a failed upload. */
  retry?: ReactNode;
  forceState?: ForceState;
  className?: string;
};



/**
 * A file attachment row. A failed row gets a red border and a red alert mark before
 * the detail line, as Carbon's invalid file does; the kind mark stays neutral.
 * The row is 320 wide and 56 high at full size.
 */
export function FileChip({
  name,
  detail,
  state = 'default',
  progress = 0,
  lead,
  remove,
  retry,
  forceState,
  className,
}: FileChipProps) {
  const forced = statesOf(forceState);
  const style = { '--file-progress': `${Math.min(Math.max(progress, 0), 1) * 100}%` } as CSSProperties;

  return (
    <div
      className={cn('file-chip', 'focus-ring', className)}
      data-state={state}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      style={style}
    >
      <span className="file-chip__lead" aria-hidden="true">
        {lead ?? <FileText />}
      </span>
      <span className="file-chip__text">
        <span className="file-chip__name">{name}</span>
        {detail === undefined && state !== 'error' ? null : (
          <span className="file-chip__detail">
            {state === 'error' ? <AlertCircle className="file-chip__alert" aria-hidden="true" /> : null}
            {detail === undefined ? null : <span className="file-chip__detail-text">{detail}</span>}
          </span>
        )}
      </span>
      {state === 'loading' ? (
        <span
          className="file-chip__bar"
          role="progressbar"
          aria-label={name}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(Math.min(Math.max(progress, 0), 1) * 100)}
        >
          <span className="file-chip__bar-fill" />
        </span>
      ) : null}
      {retry === undefined ? null : <span className="file-chip__retry">{retry}</span>}
      {remove === undefined ? null : <span className="file-chip__remove">{remove}</span>}
    </div>
  );
}
