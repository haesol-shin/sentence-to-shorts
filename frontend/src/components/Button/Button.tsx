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
  /** Called when the running control is pressed. What stopping does stays with the caller. */
  onStop?: () => void;
  iconStart?: ReactNode;
  iconEnd?: ReactNode;
  /** Forces a visual state for the gallery. Never used in a real screen. */
  forceState?: ForceState;
} & (
  | { running?: false; stopLabel?: string }
  /**
   * A job this control started is running; it becomes the stop control in
   * place, named by the caller.
   */
  | { running: boolean; stopLabel: string }
);

/**
 * One button for every screen. It forwards its ref so Base UI triggers can
 * attach to the DOM element; React 18 does not do that for a plain function.
 *
 * A control that starts a long job keeps its place while the job runs and
 * becomes its stop control there: the same height and hit area, a square mark
 * in the button's own text color, and the caller's stop label. The part does
 * not decide what stopping does.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    running = false,
    stopLabel,
    onStop,
    iconStart,
    iconEnd,
    forceState,
    className,
    type = 'button',
    disabled = false,
    onClick,
    children,
    ...rest
  },
  ref,
) {
  const forced = statesOf(forceState);
  const isRunning = running || forced.includes('loading');
  const isDisabled = disabled || forced.includes('disabled');

  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={cn('button', `button--${variant}`, `button--${size}`, 'hit-area', 'focus-ring', className)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      data-running={isRunning ? '' : undefined}
      disabled={isDisabled}
      onClick={(event) => {
        if (isRunning) {
          onStop?.();
          return;
        }
        onClick?.(event);
      }}
    >
      {isRunning ? (
        <span className="button__label">
          <span className="button__stop" aria-hidden="true">
            ■
          </span>
          {stopLabel}
        </span>
      ) : (
        <>
          {iconStart === undefined ? null : (
            <span className="button__icon" aria-hidden="true">
              {iconStart}
            </span>
          )}
          {children === undefined ? null : <span className="button__label">{children}</span>}
          {iconEnd === undefined ? null : (
            <span className="button__icon button__icon--end" aria-hidden="true">
              {iconEnd}
            </span>
          )}
        </>
      )}
    </button>
  );
});

Button.displayName = 'Button';
