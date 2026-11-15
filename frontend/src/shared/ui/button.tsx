import type { ButtonHTMLAttributes } from 'react';

import { cn } from '@/shared/lib/utils';

export type ButtonVariant = 'primary' | 'ghost';

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
};

const BASE =
  'inline-flex items-center justify-center gap-2 rounded-[var(--radius-capsule)] px-4 text-[15px] font-bold transition-colors duration-[var(--motion-short)] disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--text-strong)]';

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-[var(--text-strong)] text-[var(--surface)] hover:bg-[var(--text)] disabled:bg-[var(--text-disabled)]',
  ghost:
    'bg-transparent text-[var(--text)] hover:bg-[var(--surface-muted)] disabled:text-[var(--text-disabled)]',
};

export function Button({ variant = 'primary', className, type = 'button', ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(BASE, VARIANTS[variant], className)}
      style={{ minHeight: 'var(--touch-target)' }}
      {...rest}
    />
  );
}
