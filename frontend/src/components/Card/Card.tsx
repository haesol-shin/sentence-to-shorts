import type { ReactNode } from 'react';
import { Film } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './Card.css';

import { statesOf, type ForceState } from '../force-state';
import { LabelBox } from '../LabelBox';

export type CardVariant = 'format' | 'scene';

export type CardProps = {
  variant: CardVariant;
  /** One line under the picture, or the format name. */
  label: string;
  /** A short second line. The scene card leaves it empty. */
  description?: string;
  /** A picture or other media. The fallback is a quiet film mark. */
  media?: ReactNode;
  /** The scene number shown in the white circle. */
  number?: number;
  /** The length chip at the lower right, for example "약 3초". */
  duration?: string;
  selected?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  /** Forces a state for the gallery. */
  forceState?: ForceState;
  className?: string;
} & (
  | { busy?: false; busyLabel?: undefined }
  /**
   * The work on this card is running. A blue spinner and the caller's status
   * text show it. The header keeps its line so the card size holds.
   */
  | { busy: boolean; busyLabel: string }
);

/**
 * One selectable card. The format card is wide with a 4:3 picture; the scene
 * card is a small 9:16 picture with the scene number and one line. Selected
 * cards keep the same size: the label goes bold and the other pictures dim
 * under the approved white overlay.
 */
export function Card({
  variant,
  label,
  description,
  media,
  number,
  duration,
  selected = false,
  disabled = false,
  busy = false,
  busyLabel,
  onClick,
  forceState,
  className,
}: CardProps) {
  const forced = statesOf(forceState);
  const isSelected = selected || forced.includes('selected');
  const isDisabled = disabled || forced.includes('disabled');

  return (
    <button
      type="button"
      className={cn('card', `card--${variant}`, 'focus-ring', className)}
      aria-label={label}
      aria-pressed={isSelected}
      data-selected={isSelected ? '' : undefined}
      data-busy={busy ? '' : undefined}
      data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      disabled={isDisabled}
      onClick={onClick}
    >
      <span className="card__media" aria-hidden="true">
        {media ?? <Film className="card__fallback" />}
        <span className="card__dim" />
        {number === undefined ? null : <span className="card__number">{number}</span>}
        {duration === undefined ? null : <span className="card__duration">{duration}</span>}
      </span>
      <span className="card__label">
        {busy ? (
          <span className="card__status" role="status">
            <span className="spinner" aria-hidden="true" />
            <span className="card__status-text">{busyLabel}</span>
          </span>
        ) : (
          <LabelBox>{label}</LabelBox>
        )}
      </span>
      {description === undefined ? null : <span className="card__description">{description}</span>}
      {busy ? <span className="card__band" aria-hidden="true" /> : null}
    </button>
  );
}
