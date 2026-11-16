import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

import './Button.css';

/** The states a part receives. Gallery-only forcing; interactions use CSS. */
import { statesOf, type ForceState } from '../force-state';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'trigger';

export type ButtonSize = 'md' | 'sm';

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Keeps the label and adds a progress mark instead of a second label. */
  loading?: boolean;
  iconStart?: ReactNode;
  iconEnd?: ReactNode;
  /** Forces a visual state for the gallery. Never used in a real screen. */
  forceState?: ForceState;
};



/**
 * One button for every screen. It forwards its ref so Base UI triggers can
 * attach to the DOM element; React 18 does not do that for a plain function.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    loading = false,
    iconStart,
    iconEnd,
    forceState,
    className,
    type = 'button',
    disabled = false,
    children,
    ...rest
  },
  ref,
) {
  const forced = statesOf(forceState);
  const busy = loading || forced.includes('loading');
  const isDisabled = disabled || forced.includes('disabled');

  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={cn('button', `button--${variant}`, `button--${size}`, 'hit-area', 'focus-ring', className)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      aria-busy={busy ? true : undefined}
      disabled={isDisabled}
    >
      {iconStart === undefined ? null : (
        <span className="button__icon" aria-hidden="true">
          {iconStart}
        </span>
      )}
      {children === undefined ? null : <span className="button__label">{children}</span>}
      {busy ? <span className="spinner" aria-hidden="true" /> : null}
      {iconEnd === undefined ? null : (
        <span className="button__icon button__icon--end" aria-hidden="true">
          {iconEnd}
        </span>
      )}
    </button>
  );
});

Button.displayName = 'Button';
