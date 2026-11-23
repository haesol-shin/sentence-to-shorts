import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

import './EmptyState.css';

export type EmptyStateTone = 'neutral' | 'error';

export type EmptyStateProps = {
  title: ReactNode;
  children: ReactNode;
  tone?: EmptyStateTone;
  icon?: ReactNode;
  actions?: ReactNode;
  className?: string;
};



/**
 * A section with a title, one sentence and an action, used for an empty list
 * and for a failure that the user can recover from. No picture is drawn.
 * Callers pass secondary actions first and the primary action last.
 */
export function EmptyState({ title, children, tone = 'neutral', icon, actions, className }: EmptyStateProps) {
  return (
    <section
      className={cn('empty-state', className)}
      data-tone={tone}
      role={tone === 'error' ? 'alert' : undefined}
    >
      <h2 className="empty-state__title">
        {icon === undefined ? null : (
          <span className="empty-state__icon" aria-hidden="true">
            {icon}
          </span>
        )}
        {title}
      </h2>
      <p className="empty-state__body">{children}</p>
      {actions === undefined ? null : <div className="empty-state__actions">{actions}</div>}
    </section>
  );
}
