import { useEffect, useState } from 'react';

function panelDuration(): number {
  if (typeof document === 'undefined') return 0;
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue('--motion-panel-duration')
    .trim();
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : 0;
}

function nextFrame(callback: () => void): number {
  if (typeof window.requestAnimationFrame === 'function') {
    return window.requestAnimationFrame(callback);
  }
  return window.setTimeout(callback, 0);
}

function cancelFrame(id: number): void {
  if (typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(id);
  } else {
    window.clearTimeout(id);
  }
}

/**
 * Keeps a panel mounted through its exit movement. When open becomes true the
 * closed frame mounts in that same render, so its style exists before the two
 * frame wait switches to the open style; a lone zero timeout let the browser
 * collapse both styles and the open transition never ran. Exit waits the panel
 * duration from the tokens, then unmounts. A zero duration (reduced motion)
 * unmounts at once.
 */
export function usePresence(open: boolean): { mounted: boolean; shown: boolean } {
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      let inner: number | undefined;
      const outer = nextFrame(() => {
        inner = nextFrame(() => setShown(true));
      });
      return () => {
        cancelFrame(outer);
        if (inner !== undefined) cancelFrame(inner);
      };
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

  return { mounted: open || mounted, shown: open && shown };
}
