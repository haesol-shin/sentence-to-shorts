import type { ReactNode } from 'react';
import { AlertCircle } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './Chip.css';

import { statesOf, type ForceState } from '../force-state';
import { LabelBox } from '../LabelBox';

export type ChipState = 'default' | 'loading' | 'error';

export type ChipProps = {
  children: ReactNode;
  state?: ChipState;
  /** A small picture or file-kind mark before the name. */
  lead?: ReactNode;
  /**
   * The remove control. The caller composes a CloseButton so one component
   * owns that size in every place a chip can be closed.
   */
  remove?: ReactNode;
  forceState?: ForceState;
  className?: string;
};



/**
 * A file or value chip. The surface is not a button, so it never nests one. A failed chip
 * gets a red border and a red name, and a red alert mark takes the kind mark's place so the
 * chip keeps its width.
 */
export function Chip({ children, state = 'default', lead, remove, forceState, className }: ChipProps) {
  const forced = statesOf(forceState);
  const hasRemove = remove !== undefined;

  return (
    <div
      className={cn('chip', 'focus-ring', hasRemove && 'chip--removable', className)}
      data-state={state}
      data-no-lead={lead === undefined ? '' : undefined}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
    >
      {lead === undefined ? (
        state === 'loading' ? <span className="chip__spinner spinner" aria-hidden="true" /> : null
      ) : (
        <span className="chip__lead" aria-hidden="true">
          {state === 'loading' ? <span className="spinner" /> : state === 'error' ? <AlertCircle /> : lead}
        </span>
      )}
      <span className="chip__label">
        <LabelBox>{children}</LabelBox>
      </span>
      {hasRemove ? <span className="chip__remove">{remove}</span> : null}
    </div>
  );
}
