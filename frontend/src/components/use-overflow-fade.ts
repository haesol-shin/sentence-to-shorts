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
    const updateFade = () => {
      if (element.scrollHeight <= element.clientHeight + 8) {
        setFade('none');
        return;
      }
      const atTop = element.scrollTop <= 1;
      const atBottom = element.scrollTop + element.clientHeight >= element.scrollHeight - 1;
      setFade(atTop ? 'bottom' : atBottom ? 'top' : 'both');
    };
    // Snaps on open and on resize only; scrolling updates the fade only.
    const snap = () => {
      // Measure the room without the cap set on the last pass. Snapping the capped height
      // again rounds a fractional height (zoom, high-DPI) down one more row on each pass.
      // Clearing the cap lets the browser clamp scrollTop, so the position is kept.
      const keep = element.scrollTop;
      element.style.maxHeight = '';
      const available = element.clientHeight;
      if (element.scrollHeight <= available + 8) {
        element.scrollTop = keep;
        updateFade();
        return;
      }
      const rows = element.querySelectorAll<HTMLElement>(rowSelector);
      if (rows.length > 1) {
        const box = element.getBoundingClientRect();
        const first = rows[0].getBoundingClientRect();
        const origin = first.top - box.top + element.scrollTop;
        const pitch = rows[1].getBoundingClientRect().top - first.top;
        if (pitch > 0) {
          const snapped = Math.floor((available - origin - pitch / 2) / pitch) * pitch + pitch / 2 + origin;
          if (snapped > origin && snapped < available) element.style.maxHeight = `${snapped}px`;
        }
      }
      element.scrollTop = keep;
      updateFade();
    };
    snap();
    element.addEventListener('scroll', updateFade, { passive: true });
    // The scroller is held at its cap, so it does not resize when the window grows. Snap again
    // after the positioner has updated the available height.
    const view = element.ownerDocument.defaultView;
    let timer = 0;
    const onWindowResize = () => {
      view?.clearTimeout(timer);
      timer = view?.setTimeout(snap, 150) ?? 0;
    };
    view?.addEventListener('resize', onWindowResize);
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(snap);
    observer?.observe(element);
    return () => {
      element.removeEventListener('scroll', updateFade);
      view?.removeEventListener('resize', onWindowResize);
      view?.clearTimeout(timer);
      observer?.disconnect();
    };
  }, [element, rowSelector]);

  return fade;
}
