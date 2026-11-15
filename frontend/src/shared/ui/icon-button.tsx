import type { ButtonHTMLAttributes } from 'react';

import { cn } from '@/shared/lib/utils';

export type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** The accessible name. An icon alone carries no text. */
  label: string;
};

/**
 * A square button whose box is the touch target, so an icon never shrinks the
 * area a finger has to hit.
 */
export function IconButton({ label, className, type = 'button', ...rest }: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      className={cn(
        'inline-flex items-center justify-center rounded-[var(--radius-capsule)] text-[var(--text)] transition-colors duration-[var(--motion-short)] hover:bg-[var(--surface-muted)] disabled:cursor-not-allowed disabled:text-[var(--text-disabled)] disabled:hover:bg-transparent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--text-strong)]',
        className,
      )}
      style={{ width: 'var(--touch-target)', height: 'var(--touch-target)' }}
      {...rest}
    />
  );
}
