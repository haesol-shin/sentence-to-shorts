import type { ReactNode } from 'react';
import { Check } from 'lucide-react';
import { Switch as SwitchPrimitive } from '@base-ui/react/switch';

import { cn } from '@/shared/lib/utils';

import './Switch.css';

import { statesOf, type ForceState } from '../force-state';
import { LabelBox } from '../LabelBox';

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



/** An on/off pill. The selected look is a grey fill, bold text and a check, the same as the radio group. */
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
      <LabelBox>{children}</LabelBox>
      <Check className="switch-option__check" aria-hidden="true" />
    </SwitchPrimitive.Root>
  );
}
