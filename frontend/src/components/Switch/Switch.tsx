import type { ReactNode } from 'react';
import { Switch as SwitchPrimitive } from '@base-ui/react/switch';

import { cn } from '@/shared/lib/utils';

import './Switch.css';

import { statesOf, type ForceState } from '../force-state';

export type SwitchProps = {
  /** A visible label beside the track. The accessible name stays `label`. */
  children?: ReactNode;
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

/**
 * An on/off switch. The track is the decided 44x26 shape with a 20 knob and the
 * row keeps the 44 hit area. The selected fill and the knob position carry the
 * state; the label beside the track stays regular so the box never changes.
 */
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
      <span className="switch-option__track" aria-hidden="true">
        <span className="switch-option__thumb" />
      </span>
      {children === undefined ? null : <span className="switch-option__label">{children}</span>}
    </SwitchPrimitive.Root>
  );
}
