import type { ReactNode } from 'react';

/**
 * Reserves the wider of the regular and bold label so a selected or loading
 * state cannot change the box. The hidden copies carry the same children.
 */
export function LabelBox({ children }: { children: ReactNode }) {
  return (
    <span className="label-box">
      <span className="label-box__text">{children}</span>
      <span className="label-box__text" aria-hidden="true" data-weight="bold">
        {children}
      </span>
      <span className="label-box__text" aria-hidden="true" data-weight="regular">
        {children}
      </span>
    </span>
  );
}
