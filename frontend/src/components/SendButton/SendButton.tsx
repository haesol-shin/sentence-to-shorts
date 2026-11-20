import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { ArrowUp } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './SendButton.css';

import { statesOf, type ForceState } from '../force-state';

export type SendButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label' | 'children'> & {
  /** The accessible name when idle, for example "보내기". An icon alone carries no text. */
  label: string;
  /** The accessible name of the stop action while running. */
  stopLabel: string;
  /** The chat answer is running; the button becomes the stop control in place. */
  loading?: boolean;
  forceState?: ForceState;
};

/**
 * The composer's send control. It shows a 32px circle and fills a 44px hit area
 * through the shared ring, so the visible size stays the decided one.
 *
 * While an answer runs the same control is the stop control: a square mark in
 * the button's own text color and the caller's stop name. It stays pressable and
 * calls the caller's handler; the part does not decide what stopping does.
 */
export const SendButton = forwardRef<HTMLButtonElement, SendButtonProps>(function SendButton(
  { label, stopLabel, loading = false, forceState, className, type = 'button', disabled = false, ...rest },
  ref,
) {
  const forced = statesOf(forceState);
  const running = loading || forced.includes('loading');
  const isDisabled = disabled || forced.includes('disabled');

  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      aria-label={running ? stopLabel : label}
      className={cn('send-button', 'hit-area', 'focus-ring', className)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      data-running={running ? '' : undefined}
      disabled={isDisabled}
    >
      {running ? (
        <span className="send-button__stop" aria-hidden="true">
          ■
        </span>
      ) : (
        <ArrowUp aria-hidden="true" />
      )}
    </button>
  );
});

SendButton.displayName = 'SendButton';
