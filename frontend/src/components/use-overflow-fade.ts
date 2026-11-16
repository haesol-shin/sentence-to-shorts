import { useEffect, useState } from 'react';

export type OverflowFade = 'none' | 'bottom' | 'both' | 'top';

/**
 * The owner's overflowing-menu rule: keep half of the next row visible, fade the
 * hidden side by scroll position, and do not draw a scrollbar. The scroll element
 * is snapped to a half-row height only while it overflows.
 */
export function useOverflowFade(element: HTMLElement | null, rowSelector: string): OverflowFade {
  const [fade, setFade] = useState<OverflowFade>('none');

  useEffect(() => {
    if (element === null) return;
    const update = () => {
      if (element.scrollHeight <= element.clientHeight + 8) {
        element.style.maxHeight = '';
        setFade('none');
        return;
      }
      const rows = element.querySelectorAll<HTMLElement>(rowSelector);
      if (rows.length === 0) return;
      const box = element.getBoundingClientRect();
      const first = rows[0].getBoundingClientRect();
      const origin = first.top - box.top + element.scrollTop;
      const pitch = rows.length > 1 ? rows[1].getBoundingClientRect().top - first.top : 0;
      const available = element.clientHeight;
      if (pitch > 0) {
        const snapped = Math.floor((available - origin - pitch / 2) / pitch) * pitch + pitch / 2 + origin;
        if (snapped > origin && snapped < available) element.style.maxHeight = `${snapped}px`;
      }
      const atTop = element.scrollTop <= 1;
      const atBottom = element.scrollTop + element.clientHeight >= element.scrollHeight - 1;
      setFade(atTop ? 'bottom' : atBottom ? 'top' : 'both');
    };
    update();
    element.addEventListener('scroll', update, { passive: true });
    if (typeof ResizeObserver === 'undefined') {
      return () => element.removeEventListener('scroll', update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => {
      element.removeEventListener('scroll', update);
      observer.disconnect();
    };
  }, [element, rowSelector]);

  return fade;
}
