import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { X } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './CloseButton.css';

import { statesOf, type ForceState } from '../force-state';

export type CloseButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label' | 'children'> & {
  /** The accessible name, for example "닫기" or "파일 지우기". */
  label: string;
  /** `sm` sits in a 36px file chip. `md` closes a panel or a window. */
  size?: 'sm' | 'md';
  forceState?: ForceState;
};



/** One close x for panels, windows and file chips; only the visible size changes. */
export const CloseButton = forwardRef<HTMLButtonElement, CloseButtonProps>(function CloseButton(
  { label, size = 'md', forceState, className, type = 'button', disabled = false, ...rest },
  ref,
) {
  const forced = statesOf(forceState);
  const isDisabled = disabled || forced.includes('disabled');

  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      aria-label={label}
      className={cn('close-button', `close-button--${size}`, 'hit-area', 'focus-ring', className)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      disabled={isDisabled}
    >
      <X aria-hidden="true" />
    </button>
  );
});

CloseButton.displayName = 'CloseButton';
