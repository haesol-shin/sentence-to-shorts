import { forwardRef, useId, type InputHTMLAttributes } from 'react';
import { Input as InputPrimitive } from '@base-ui/react/input';
import { AlertCircle } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './TextField.css';

export type ForceState = string | readonly string[];

export type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'aria-label' | 'children'> & {
  /** The visible label, also the accessible name. */
  label: string;
  /** A sentence about what went wrong and how to fix it. */
  error?: string;
  forceState?: ForceState;
  className?: string;
};

function statesOf(value?: ForceState): readonly string[] {
  if (value === undefined) return [];
  return typeof value === 'string' ? value.split(/\s+/).filter(Boolean) : value;
}

/** A one-line input. The error sentence is wired to the input, not only drawn. */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, error, forceState, className, id, disabled = false, ...rest },
  ref,
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = `${inputId}-error`;
  const forced = statesOf(forceState);
  const isDisabled = disabled || forced.includes('disabled');

  return (
    <div
      className={cn('text-field', className)}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
    >
      <label className="text-field__label" htmlFor={inputId}>
        {label}
      </label>
      <InputPrimitive
        {...rest}
        ref={ref}
        id={inputId}
        className="text-field__input"
        aria-invalid={error === undefined ? undefined : true}
        aria-describedby={error === undefined ? undefined : errorId}
        disabled={isDisabled}
      />
      {error === undefined ? null : (
        <p className="text-field__error" id={errorId}>
          <AlertCircle aria-hidden="true" />
          <span>{error}</span>
        </p>
      )}
    </div>
  );
});

TextField.displayName = 'TextField';
