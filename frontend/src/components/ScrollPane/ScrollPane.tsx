import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { ChevronDown } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './ScrollPane.css';

import { IconButton } from '../IconButton/IconButton';

export type ScrollPaneProps = {
  /** The accessible name of the scrolling region. */
  label: string;
  /** The accessible name of the floating jump control. */
  jumpLabel: string;
  children: ReactNode;
  className?: string;
};

/**
 * One scrolling column. The scrollbar is never drawn, while the wheel, the
 * trackpad and the keyboard scroll it as usual. When more content waits below,
 * a 44 round jump control named by the caller sits at the bottom centre and moves one
 * screen's 80 percent; at the end it disappears and gives focus back to the
 * column. In the app the control has its own dock row under the column, so it
 * never covers content or a caller's controls; outside the app the dock has no
 * height and the control floats over the column.
 */
export const ScrollPane = forwardRef<HTMLDivElement, ScrollPaneProps>(
  function ScrollPane({ label, jumpLabel, children, className }, ref) {
    const viewportRef = useRef<HTMLDivElement>(null);
    const jumpRef = useRef<HTMLButtonElement>(null);
    const jumpWrapRef = useRef<HTMLDivElement>(null);
    const [more, setMore] = useState(false);

    useImperativeHandle(ref, () => viewportRef.current as HTMLDivElement, []);

    const update = useCallback(() => {
      const viewport = viewportRef.current;
      if (viewport === null) return;
      const next = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight > 1;
      // Keep the keyboard in the column when the focused control is removed.
      if (!next && jumpRef.current !== null && viewport.ownerDocument.activeElement === jumpRef.current) {
        viewport.focus({ preventScroll: true });
      }
      setMore(next);
    }, []);

    useEffect(() => {
      const viewport = viewportRef.current;
      if (viewport === null) return undefined;
      update();
      viewport.addEventListener('scroll', update, { passive: true });
      const content = viewport.firstElementChild;
      const observer =
        typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(update);
      observer?.observe(viewport);
      if (content !== null) observer?.observe(content);
      return () => {
        viewport.removeEventListener('scroll', update);
        observer?.disconnect();
      };
    }, [update]);

    useEffect(() => {
      const wrap = jumpWrapRef.current;
      const viewport = viewportRef.current;
      if (wrap === null || viewport === null) return undefined;
      // The control floats over the column, so send a plain vertical wheel to the column.
      // Zoom and horizontal or modified gestures stay with the browser.
      const onWheel = (event: WheelEvent) => {
        if (event.ctrlKey || event.shiftKey || event.altKey || event.metaKey) return;
        if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
        const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1;
        const before = viewport.scrollTop;
        const limit = viewport.scrollHeight - viewport.clientHeight;
        const target = Math.max(0, Math.min(before + event.deltaY * unit, limit));
        if (target === before) return;
        event.preventDefault();
        // The column smooth-scrolls for the jump control; a wheel step stays immediate.
        viewport.scrollTo({ top: target, behavior: 'instant' });
      };
      // The floating button keeps focus while it stays visible, so its scroll keys
      // must move the column instead of the page behind it.
      const onKeyDown = (event: KeyboardEvent) => {
        const step = event.key === 'ArrowDown' ? 1 : event.key === 'ArrowUp' ? -1 : 0;
        const page = event.key === 'PageDown' ? 1 : event.key === 'PageUp' ? -1 : 0;
        if (step === 0 && page === 0 && event.key !== 'Home' && event.key !== 'End') return;
        event.preventDefault();
        const limit = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
        // Key steps apply at once so held keys accumulate; the jump keeps its smooth move.
        if (event.key === 'Home') viewport.scrollTo({ top: 0, behavior: 'instant' });
        else if (event.key === 'End') viewport.scrollTo({ top: limit, behavior: 'instant' });
        else if (page !== 0) {
          viewport.scrollBy({ top: viewport.clientHeight * 0.9 * page, behavior: 'instant' });
        } else viewport.scrollBy({ top: step * 40, behavior: 'instant' });
      };
      wrap.addEventListener('wheel', onWheel, { passive: false });
      wrap.addEventListener('keydown', onKeyDown);
      return () => {
        wrap.removeEventListener('wheel', onWheel);
        wrap.removeEventListener('keydown', onKeyDown);
      };
    }, [more]);

    const jump = () => {
      const viewport = viewportRef.current;
      if (viewport === null) return;
      viewport.scrollBy({ top: viewport.clientHeight * 0.8 });
    };

    return (
      <div className={cn('scroll-pane', className)}>
        <div
          ref={viewportRef}
          className="scroll-pane__viewport focus-ring focus-ring--inset"
          role="region"
          aria-label={label}
          tabIndex={0}
        >
          <div className="scroll-pane__content">{children}</div>
        </div>
        {more ? (
          <div ref={jumpWrapRef} className="scroll-pane__jump">
            <div className="scroll-pane__jump-button">
              <IconButton ref={jumpRef} label={jumpLabel} onClick={jump}>
                <ChevronDown aria-hidden="true" />
              </IconButton>
            </div>
          </div>
        ) : null}
      </div>
    );
  },
);

ScrollPane.displayName = 'ScrollPane';
