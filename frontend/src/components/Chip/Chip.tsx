import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

import './Chip.css';

export type ForceState = string | readonly string[];

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

function statesOf(value?: ForceState): readonly string[] {
  if (value === undefined) return [];
  return typeof value === 'string' ? value.split(/\s+/).filter(Boolean) : value;
}

/** A file or value chip. The surface is not a button, so it never nests one. */
export function Chip({ children, state = 'default', lead, remove, forceState, className }: ChipProps) {
  const forced = statesOf(forceState);
  const hasRemove = remove !== undefined;

  return (
    <div
      className={cn('chip', 'focus-ring', hasRemove && 'chip--removable', className)}
      data-state={state}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
    >
      {lead === undefined && state !== 'loading' ? null : (
        <span className="chip__lead" aria-hidden="true">
          {state === 'loading' ? <span className="spinner" /> : lead}
        </span>
      )}
      <span
        className="chip__label"
        data-label={typeof children === 'string' ? children : undefined}
      >
        <span className="chip__text">{children}</span>
      </span>
      {hasRemove ? <span className="chip__remove">{remove}</span> : null}
    </div>
  );
}
