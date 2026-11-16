import type { ReactNode } from 'react';
import { AlertCircle, AlertTriangle, Info } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './Notice.css';

export type NoticeTone = 'neutral' | 'warning' | 'error';

export type NoticeProps = {
  tone?: NoticeTone;
  title?: ReactNode;
  children: ReactNode;
  className?: string;
};

const ICON = {
  neutral: Info,
  warning: AlertTriangle,
  error: AlertCircle,
};

/**
 * A short note on a grey surface. The tone colours the icon only, so the text
 * keeps its contrast on that surface.
 */
export function Notice({ tone = 'neutral', title, children, className }: NoticeProps) {
  const Icon = ICON[tone];

  return (
    <div
      className={cn('notice', `notice--${tone}`, className)}
      data-tone={tone}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      <span className="notice__icon" aria-hidden="true">
        <Icon />
      </span>
      <div className="notice__content">
        {title === undefined ? null : <p className="notice__title">{title}</p>}
        <p className="notice__body">{children}</p>
      </div>
    </div>
  );
}
