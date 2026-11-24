import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

import './IconButton.css';

import { statesOf, type ForceState } from '../force-state';

export type IconButtonSize = 'default' | '36' | 'compact' | '24';

export type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> & {
  /** The accessible name. An icon alone carries no text. */
  label: string;
  /**
   * `36` draws the scene tools of a script card, `compact` draws 32 for controls inside a row or a field,
   * and `24` draws the delete corner of a scene card. Every size keeps the 44 hit area.
   */
  size?: IconButtonSize;
  selected?: boolean;
  forceState?: ForceState;
  children: ReactNode;
};



/** A 44x44 icon control; the smaller sizes keep the 44 hit area. The icon never shrinks the box. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, size = 'default', selected = false, forceState, className, type = 'button', disabled = false, children, ...rest },
  ref,
) {
  const forced = statesOf(forceState);
  const isSelected = selected || forced.includes('selected');
  const isDisabled = disabled || forced.includes('disabled');

  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      aria-label={label}
      aria-pressed={isSelected ? true : undefined}
      className={cn('icon-button', `icon-button--${size}`, 'hit-area', 'focus-ring', className)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      disabled={isDisabled}
    >
      {children}
    </button>
  );
});

IconButton.displayName = 'IconButton';
