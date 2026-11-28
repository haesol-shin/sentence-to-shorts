import { createContext, useContext, useEffect, useLayoutEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/shared/lib/utils';

import { usePresence } from '../use-presence';

import './Toast.css';

export type ToastProps = {
  open: boolean;
  children: ReactNode;
  className?: string;
  durationMs?: number;
};



export const ToastAnchor = createContext<HTMLElement | null>(null);

/** A short confirmation at the bottom centre of the work surface. */
export function Toast({ open, children, className, durationMs }: ToastProps) {
  const anchor = useContext(ToastAnchor);
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    setExpired(false);
    if (!open || durationMs === undefined) return;
    const timer = window.setTimeout(() => setExpired(true), durationMs);
    return () => window.clearTimeout(timer);
  }, [open, durationMs]);
  const { mounted, shown } = usePresence(open && !expired);
  const [bounds, setBounds] = useState<{ left: number; width: number }>();
  useLayoutEffect(() => {
    if (!mounted || anchor === null) return;
    const place = () => {
      const { left, width } = anchor.getBoundingClientRect();
      setBounds({ left: left + width / 2, width });
    };
    place();
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(place);
    observer?.observe(anchor);
    if (anchor.parentElement !== null) observer?.observe(anchor.parentElement);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('resize', place);
      observer?.disconnect();
    };
  }, [anchor, mounted]);
  if (!mounted) return null;

  const content = (
    <div
      className={cn('toast-surface', className)}
      role="status"
      aria-live="polite"
      data-state={shown ? 'open' : 'closed'}
      style={anchor === null || bounds === undefined ? undefined : { left: bounds.left, maxWidth: `calc(${bounds.width}px - var(--space-48))` }}
    >
      {children}
    </div>
  );

  return typeof document === 'undefined' ? content : createPortal(content, document.body);
}
