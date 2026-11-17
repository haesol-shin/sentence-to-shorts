import { cn } from '@/shared/lib/utils';

import './StageIndicator.css';

import { statesOf, type ForceState } from '../force-state';
import { LabelBox } from '../LabelBox';

export type StageOption = {
  value: string;
  label: string;
};

export type StageIndicatorProps = {
  /** The accessible name of the step navigation. */
  label: string;
  stages: readonly StageOption[];
  current: string;
  /** A past step returns to that stage. Upcoming steps are not pressable. */
  onSelect?: (value: string) => void;
  /** Forces a state on the past steps for the gallery. */
  forceState?: ForceState;
  /** Shows that forced state on one past step only. */
  forceStep?: string;
  className?: string;
};

/**
 * The four stage names. The current stage is bold with a dot under it; a past
 * stage is a button that moves back; an upcoming stage is a lighter label. The
 * label box reserves the bold width so moving the dot and weight cannot shift
 * the row.
 */
export function StageIndicator({
  label,
  stages,
  current,
  onSelect,
  forceState,
  forceStep,
  className,
}: StageIndicatorProps) {
  const forced = statesOf(forceState);
  const forcedAttr = forced.length > 0 ? forced.join(' ') : undefined;
  const currentIndex = stages.findIndex((stage) => stage.value === current);

  return (
    <nav className={cn('stage-indicator', className)} aria-label={label} data-current={current}>
      {stages.map((stage, index) => {
        const isCurrent = stage.value === current;
        const isPast = index < currentIndex;
        const content = (
          <>
            <span className="stage-indicator__label">
              <LabelBox>{stage.label}</LabelBox>
            </span>
            <span className="stage-indicator__dot" aria-hidden="true" />
          </>
        );

        if (isCurrent) {
          return (
            <span
              key={stage.value}
              className="stage-indicator__step stage-indicator__step--current"
              aria-current="step"
            >
              {content}
            </span>
          );
        }

        if (isPast) {
          return (
            <button
              key={stage.value}
              type="button"
              className="stage-indicator__step stage-indicator__step--past hit-area focus-ring"
              data-force-state={forceStep === undefined || forceStep === stage.value ? forcedAttr : undefined}
              onClick={() => onSelect?.(stage.value)}
            >
              {content}
            </button>
          );
        }

        return (
          <span key={stage.value} className="stage-indicator__step stage-indicator__step--upcoming">
            {content}
          </span>
        );
      })}
    </nav>
  );
}
