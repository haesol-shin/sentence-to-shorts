import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

export type ChipState = 'value' | 'placeholder';

/**
 * A small label in a box. `placeholder` marks a control the shell shows but
 * cannot use yet, so it reads grey instead of pretending to work.
 */
export function Chip({
  state = 'value',
  className,
  children,
}: {
  state?: ChipState;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      data-state={state}
      aria-disabled={state === 'placeholder' ? true : undefined}
      className={cn(
        'inline-flex min-h-8 items-center gap-1 rounded-[var(--radius-capsule)] px-3 text-[15px] whitespace-nowrap',
        state === 'value' && 'bg-[var(--surface-muted)] text-[var(--text)]',
        state === 'placeholder' && 'bg-transparent text-[var(--text-disabled)]',
        className,
      )}
    >
      {children}
    </span>
  );
}
