import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

import './Tag.css';

export type TagVariant = 'neutral' | 'new' | 'warning' | 'error';

export type TagProps = {
  variant?: TagVariant;
  /** A meaning mark. Its colour carries the tone; the text stays foreground. */
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
};

/**
 * A pill label. The tone lives on the icon so the text keeps its contrast on grey. The new
 * variant draws its own dot, so every caller gets the same mark.
 */
export function Tag({ variant = 'neutral', icon, children, className }: TagProps) {
  const mark = variant === 'new' ? <span className="tag__dot" /> : icon;
  return (
    <span className={cn('tag', 'hit-area', `tag--${variant}`, className)} data-variant={variant}>
      {mark === undefined ? null : (
        <span className="tag__icon" aria-hidden="true">
          {mark}
        </span>
      )}
      <span className="tag__label">{children}</span>
    </span>
  );
}
