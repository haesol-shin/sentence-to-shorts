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

/** A pill label. The tone lives on the icon so the text keeps its contrast on grey. */
export function Tag({ variant = 'neutral', icon, children, className }: TagProps) {
  return (
    <span className={cn('tag', `tag--${variant}`, className)} data-variant={variant}>
      {icon === undefined ? null : (
        <span className="tag__icon" aria-hidden="true">
          {icon}
        </span>
      )}
      <span className="tag__label">{children}</span>
    </span>
  );
}
