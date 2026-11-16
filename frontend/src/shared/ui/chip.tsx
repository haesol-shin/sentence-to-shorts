import type { HTMLAttributes } from 'react';

import { cn } from '@/shared/lib/utils';

export type ChipState = 'value' | 'placeholder';

export type ChipProps = HTMLAttributes<HTMLSpanElement> & {
  state?: ChipState;
  [key: `data-${string}`]: string | number | undefined;
};

/**
 * A small label in a box. `placeholder` marks a control the shell shows but
 * cannot use yet, so it reads grey instead of pretending to work. Every input
 * chip keeps the same 36px height in the first screen and the conversation rail.
 */
export function Chip({ state = 'value', className, children, ...rest }: ChipProps) {
  return (
    <span
      data-state={state}
      aria-disabled={state === 'placeholder' ? true : undefined}
      {...rest}
      className={cn(
        'inline-flex h-9 items-center gap-1 rounded-[var(--radius-capsule)] px-3 text-[15px] whitespace-nowrap',
        state === 'value' && 'bg-[var(--surface-muted)] text-[var(--text)]',
        state === 'placeholder' && 'bg-transparent text-[var(--text-disabled)]',
        className,
      )}
    >
      {children}
    </span>
  );
}
