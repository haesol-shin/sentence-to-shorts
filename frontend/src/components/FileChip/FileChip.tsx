import type { CSSProperties, ReactNode } from 'react';
import { FileText } from 'lucide-react';

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
 * A file attachment row. The kind mark stays neutral on failure so the one red
 * sentence is the detail line. The row is 320 wide and 56 high at full size.
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
        {detail === undefined ? null : <span className="file-chip__detail">{detail}</span>}
      </span>
      {state === 'loading' ? (
        <span className="file-chip__bar" aria-hidden="true">
          <span className="file-chip__bar-fill" />
        </span>
      ) : null}
      {retry === undefined ? null : <span className="file-chip__retry">{retry}</span>}
      {remove === undefined ? null : <span className="file-chip__remove">{remove}</span>}
    </div>
  );
}
