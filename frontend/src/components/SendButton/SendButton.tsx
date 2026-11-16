import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { ArrowUp } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './SendButton.css';

import { statesOf, type ForceState } from '../force-state';

export type SendButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label' | 'children'> & {
  /** The accessible name, for example "보내기". An icon alone carries no text. */
  label: string;
  loading?: boolean;
  forceState?: ForceState;
};



/**
 * The composer's send control. It shows a 32px circle and fills a 44px hit area
 * through the shared ring, so the visible size stays the decided one.
 */
export const SendButton = forwardRef<HTMLButtonElement, SendButtonProps>(function SendButton(
  { label, loading = false, forceState, className, type = 'button', disabled = false, ...rest },
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
      aria-label={label}
      aria-busy={busy ? true : undefined}
      className={cn('send-button', 'hit-area', 'focus-ring', className)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      disabled={isDisabled}
    >
      {busy ? <span className="spinner" aria-hidden="true" /> : <ArrowUp aria-hidden="true" />}
    </button>
  );
});

SendButton.displayName = 'SendButton';
