import { Progress as ProgressPrimitive } from '@base-ui/react/progress';

import { cn } from '@/shared/lib/utils';

import './Progress.css';

export type ProgressProps = {
  /** The progress value. `null` means the work has no measurable amount yet. */
  value: number | null;
  max?: number;
  /** The visible label. It is also the accessible name. */
  label?: string;
  /** Overrides the accessible name when the visible label is not enough. */
  labelText?: string;
  /** Replaces the percentage, for example "3 / 5". The bar still follows value and max. */
  valueText?: string;
  className?: string;
};



/**
 * A 6px progress track. The track is the muted surface and the fill is the
 * foreground, both from the state table. The text and its count use the
 * progress token. The value is announced to screen readers; the text keeps
 * the numbers in one width.
 */
export function Progress({ value, max = 100, label, labelText, valueText, className }: ProgressProps) {
  return (
    <ProgressPrimitive.Root
      value={value}
      max={max}
      className={cn('progress', className)}
      aria-label={labelText ?? label}
    >
      {label === undefined ? null : (
        <div className="progress__meta">
          <ProgressPrimitive.Label className="progress__label">{label}</ProgressPrimitive.Label>
          <ProgressPrimitive.Value className="progress__value">
            {() =>
              valueText ?? (value === null ? '진행 중' : `${Math.round((value / max) * 100)}%`)
            }
          </ProgressPrimitive.Value>
        </div>
      )}
      <ProgressPrimitive.Track className="progress__track">
        <ProgressPrimitive.Indicator className="progress__indicator" />
      </ProgressPrimitive.Track>
    </ProgressPrimitive.Root>
  );
}
