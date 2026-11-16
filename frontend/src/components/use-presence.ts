import { useEffect, useState } from 'react';

function panelDuration(): number {
  if (typeof document === 'undefined') return 0;
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue('--motion-panel-duration')
    .trim();
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : 0;
}

/**
 * Keeps a panel mounted through its exit movement. Enter starts one frame
 * after mount so the closed style paints first; exit waits the panel duration
 * from the tokens, then unmounts. A zero duration (reduced motion) unmounts at
 * once.
 */
export function usePresence(open: boolean): { mounted: boolean; shown: boolean } {
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      const timer = window.setTimeout(() => setShown(true), 0);
      return () => window.clearTimeout(timer);
    }

    setShown(false);
    let timer: number | undefined;
    const ms = panelDuration();
    if (ms <= 0) {
      setMounted(false);
    } else {
      timer = window.setTimeout(() => setMounted(false), ms);
    }
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [open]);

  return { mounted, shown: open && shown };
}
