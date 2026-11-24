import type { ReactNode } from 'react';

/**
 * Reserves the wider of the regular and bold label so a selected or loading
 * state cannot change the box. The hidden copies carry the same children; a
 * plain text label draws them from an attribute, so its words are on the page
 * once and a text search finds the label itself.
 */
export function LabelBox({ children }: { children: ReactNode }) {
  const text = typeof children === 'string' ? children : undefined;
  const copy = text === undefined ? children : null;
  return (
    <span className="label-box">
      <span className="label-box__text">{children}</span>
      <span className="label-box__text" aria-hidden="true" data-weight="bold" data-label={text}>
        {copy}
      </span>
      <span className="label-box__text" aria-hidden="true" data-weight="regular" data-label={text}>
        {copy}
      </span>
    </span>
  );
}
