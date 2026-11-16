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
      const pitch = rows.length > 1 ? rows[1].offsetTop - rows[0].offsetTop : 0;
      const available = element.clientHeight;
      if (pitch > 0) {
        const snapped = Math.floor((available - pitch / 2) / pitch) * pitch + pitch / 2;
        if (snapped >= pitch && snapped < available) element.style.maxHeight = `${snapped}px`;
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
