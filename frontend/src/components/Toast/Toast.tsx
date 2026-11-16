import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/shared/lib/utils';

import { usePresence } from '../use-presence';

import './Toast.css';

export type ToastProps = {
  open: boolean;
  children: ReactNode;
  className?: string;
};



/** A short confirmation at the bottom centre. It stays one 44px line. */
export function Toast({ open, children, className }: ToastProps) {
  const { mounted, shown } = usePresence(open);
  if (!mounted) return null;

  const content = (
    <div
      className={cn('toast-surface', className)}
      role="status"
      aria-live="polite"
      data-state={shown ? 'open' : 'closed'}
    >
      {children}
    </div>
  );

  return typeof document === 'undefined' ? content : createPortal(content, document.body);
}
