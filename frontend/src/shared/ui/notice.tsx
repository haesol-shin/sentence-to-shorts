import { X } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import { IconButton } from './icon-button';

export type NoticeTone = 'info' | 'error';

/**
 * One line about the state of the app. The tone is a hook for the design
 * track; the shell itself only draws greys.
 */
export function Notice({
  tone,
  message,
  onDismiss,
  dismissLabel,
  className,
}: {
  tone: NoticeTone;
  message: string;
  onDismiss?: () => void;
  dismissLabel?: string;
  className?: string;
}) {
  return (
    <div
      data-tone={tone}
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn(
        'flex items-center gap-2 bg-[var(--surface-muted)] px-4 py-1 text-[15px] text-[var(--text)]',
        className,
      )}
    >
      <p className="min-w-0 flex-1">{message}</p>
      {onDismiss !== undefined && dismissLabel !== undefined ? (
        <IconButton label={dismissLabel} onClick={onDismiss} className="shrink-0">
          <X aria-hidden size={18} />
        </IconButton>
      ) : null}
    </div>
  );
}
