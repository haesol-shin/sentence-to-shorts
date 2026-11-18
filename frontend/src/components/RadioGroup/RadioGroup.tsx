import { Radio as RadioPrimitive } from '@base-ui/react/radio';
import { RadioGroup as RadioGroupPrimitive } from '@base-ui/react/radio-group';
import { Check } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './RadioGroup.css';

import { LabelBox } from '../LabelBox';

import { statesOf, type ForceState } from '../force-state';

export type RadioOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

export type RadioGroupProps = {
  /** The accessible name of the group. */
  label: string;
  options: readonly RadioOption[];
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  /** Forces a state on the first option for the gallery. */
  forceState?: ForceState;
  className?: string;
};



/** One choice out of a few. Arrow keys move the choice; the dot marks it. */
export function RadioGroup({
  label,
  options,
  value,
  defaultValue,
  onValueChange,
  forceState,
  className,
}: RadioGroupProps) {
  const forced = statesOf(forceState);
  const forcedAttr = forced.length > 0 ? forced.join(' ') : undefined;

  return (
    <RadioGroupPrimitive
      className={cn('radio-group', className)}
      aria-label={label}
      value={value}
      defaultValue={defaultValue}
      onValueChange={(next) => onValueChange?.(String(next))}
    >
      {options.map((option, index) => (
        <RadioPrimitive.Root
          key={option.value}
          value={option.value}
          disabled={option.disabled}
          className="radio-option hit-area focus-ring"
          data-force-state={index === 0 ? forcedAttr : undefined}
        >
          <span className="radio-option__label">
            <LabelBox>{option.label}</LabelBox>
          </span>
          <Check className="radio-option__check" aria-hidden="true" />
        </RadioPrimitive.Root>
      ))}
    </RadioGroupPrimitive>
  );
}
