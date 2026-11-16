import { Radio as RadioPrimitive } from '@base-ui/react/radio';
import { RadioGroup as RadioGroupPrimitive } from '@base-ui/react/radio-group';

import { cn } from '@/shared/lib/utils';

import './RadioGroup.css';

export type ForceState = string | readonly string[];

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

function statesOf(value?: ForceState): readonly string[] {
  if (value === undefined) return [];
  return typeof value === 'string' ? value.split(/\s+/).filter(Boolean) : value;
}

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
          <span className="radio-option__mark" aria-hidden="true">
            <span className="radio-option__dot" />
          </span>
          <span className="radio-option__label">{option.label}</span>
        </RadioPrimitive.Root>
      ))}
    </RadioGroupPrimitive>
  );
}
