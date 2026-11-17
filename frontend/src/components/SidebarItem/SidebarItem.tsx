import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

import './SidebarItem.css';

import { statesOf, type ForceState } from '../force-state';

export type SidebarItemProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> & {
  /** The accessible name. The rail shows the icon only; the name is a tooltip. */
  label: string;
  selected?: boolean;
  forceState?: ForceState;
  children: ReactNode;
};

/**
 * One icon item in the collapsed rail. The box is 44x44, the icon is 20, and
 * the selected state is the navigation current page. The caller adds the
 * shared tooltip when the name must be visible on hover.
 */
export const SidebarItem = forwardRef<HTMLButtonElement, SidebarItemProps>(function SidebarItem(
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
      aria-current={isSelected ? 'page' : undefined}
      className={cn('sidebar-item', 'hit-area', 'focus-ring', className)}
      data-selected={isSelected ? '' : undefined}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      disabled={isDisabled}
    >
      <span className="sidebar-item__icon" aria-hidden="true">
        {children}
      </span>
    </button>
  );
});

SidebarItem.displayName = 'SidebarItem';
