import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './TopBarItem.css';

import { statesOf, type ForceState } from '../force-state';
import { LabelBox } from '../LabelBox';

export type TopBarItemProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> & {
  label: string;
  iconStart?: ReactNode;
  /** Defaults to the down chevron used by the project name and video settings. */
  iconEnd?: ReactNode;
  forceState?: ForceState;
};

/**
 * A flat top bar item. It is 44 high and has no background until hover or open,
 * so the bar reads as text on the app surface. It forwards its ref because the
 * same item opens menus and panels.
 */
export const TopBarItem = forwardRef<HTMLButtonElement, TopBarItemProps>(function TopBarItem(
  { label, iconStart, iconEnd, forceState, className, type = 'button', disabled = false, children, ...rest },
  ref,
) {
  const forced = statesOf(forceState);
  const isDisabled = disabled || forced.includes('disabled');
  const end = iconEnd === undefined ? <ChevronDown aria-hidden="true" /> : iconEnd;

  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={cn('top-bar-item', 'hit-area', 'focus-ring', className)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      disabled={isDisabled}
    >
      {iconStart === undefined ? null : (
        <span className="top-bar-item__icon" aria-hidden="true">
          {iconStart}
        </span>
      )}
      <span className="top-bar-item__label">
        <LabelBox>{children ?? label}</LabelBox>
      </span>
      {end === null ? null : (
        <span className="top-bar-item__icon top-bar-item__icon--end" aria-hidden="true">
          {end}
        </span>
      )}
    </button>
  );
});

TopBarItem.displayName = 'TopBarItem';
