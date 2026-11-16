import type { ReactNode } from 'react';
import { Switch as SwitchPrimitive } from '@base-ui/react/switch';

import { cn } from '@/shared/lib/utils';

import './Switch.css';

export type ForceState = string | readonly string[];

export type SwitchProps = {
  children: ReactNode;
  /** Used when the visible text is not enough on its own. */
  label?: string;
  checked?: boolean;
  defaultChecked?: boolean;
  disabled?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  /** Forces a state on the control for the gallery. */
  forceState?: ForceState;
  className?: string;
};

function statesOf(value?: ForceState): readonly string[] {
  if (value === undefined) return [];
  return typeof value === 'string' ? value.split(/\s+/).filter(Boolean) : value;
}

/** An on/off pill. The selected look is a grey fill with bold text from the state table. */
export function Switch({
  children,
  label,
  checked,
  defaultChecked,
  disabled = false,
  onCheckedChange,
  forceState,
  className,
}: SwitchProps) {
  const forced = statesOf(forceState);
  const isDisabled = disabled || forced.includes('disabled');

  return (
    <SwitchPrimitive.Root
      className={cn('switch-option', 'hit-area', 'focus-ring', className)}
      aria-label={label}
      checked={checked}
      defaultChecked={defaultChecked}
      disabled={isDisabled}
      onCheckedChange={(next) => onCheckedChange?.(next)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
    >
      <span className="switch-option__label" data-label={typeof children === 'string' ? children : undefined}>
        {children}
      </span>
    </SwitchPrimitive.Root>
  );
}
