import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

import './IconButton.css';

import { statesOf, type ForceState } from '../force-state';

export type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> & {
  /** The accessible name. An icon alone carries no text. */
  label: string;
  selected?: boolean;
  forceState?: ForceState;
  children: ReactNode;
};



/** A 44x44 icon control. The box is the hit area, so the icon never shrinks it. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, selected = false, forceState, className, type = 'button', disabled = false, children, ...rest },
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
      className={cn('icon-button', 'focus-ring', className)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      disabled={isDisabled}
    >
      {children}
    </button>
  );
});

IconButton.displayName = 'IconButton';
