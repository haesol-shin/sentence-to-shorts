import { useState, type ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

export type TooltipSide = 'right' | 'top';

/**
 * Names an icon on hover and on keyboard focus. The trigger keeps its own
 * accessible name, so the bubble is a visual aid rather than the only label.
 */
export function Tooltip({
  label,
  side = 'top',
  className,
  children,
}: {
  label: string;
  side?: TooltipSide;
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <span
      className={cn('relative inline-flex', className)}
      onPointerEnter={() => setOpen(true)}
      onPointerLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open ? (
        <span
          role="tooltip"
          className={cn(
            'pointer-events-none absolute z-20 w-max max-w-56 rounded-[var(--radius-panel)] bg-[var(--text-strong)] px-3 py-2 text-[15px] text-[var(--surface)]',
            side === 'right' && 'top-1/2 left-[calc(100%+8px)] -translate-y-1/2',
            side === 'top' && 'bottom-[calc(100%+8px)] left-1/2 -translate-x-1/2',
          )}
        >
          {label}
        </span>
      ) : null}
    </span>
  );
}
