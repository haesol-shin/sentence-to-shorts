import { cloneElement, useEffect, useId, useState, type ReactElement, type ReactNode } from 'react';
import { Tooltip as TooltipPrimitive } from '@base-ui/react/tooltip';

import { cn } from '@/shared/lib/utils';

import './Tooltip.css';

export type TooltipSide = 'top' | 'bottom' | 'left' | 'right';

export type TooltipProps = {
  content: ReactNode;
  /** A control that forwards its ref, so the trigger keeps its aria-expanded. */
  children: ReactElement;
  side?: TooltipSide;
  /** Opens for the gallery without hover. */
  forceOpen?: boolean;
  className?: string;
};

/**
 * A short reason on hover and on keyboard focus. One line is a pill; two lines
 * or more use the content radius, both from the token set.
 */
export function Tooltip({ content, children, side = 'top', forceOpen, className }: TooltipProps) {
  const [open, setOpen] = useState(forceOpen ?? false);
  const [lines, setLines] = useState(1);
  const [popup, setPopup] = useState<HTMLDivElement | null>(null);
  const popupId = useId();
  const shown = forceOpen ?? open;

  useEffect(() => {
    if (forceOpen !== undefined) setOpen(forceOpen);
  }, [forceOpen]);

  useEffect(() => {
    if (!shown || popup === null) return;
    const measure = () => setLines(popup.offsetHeight > 44 ? 2 : 1);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(popup);
    return () => observer.disconnect();
  }, [shown, popup, content]);

  return (
    <TooltipPrimitive.Root
      open={shown}
      onOpenChange={(next) => {
        if (forceOpen === undefined) setOpen(next);
      }}
    >
      <TooltipPrimitive.Trigger
        render={cloneElement(children, { 'aria-describedby': shown ? popupId : undefined })}
      />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner side={side} sideOffset={8} collisionPadding={8} className="tooltip-positioner">
          <TooltipPrimitive.Popup
            ref={setPopup}
            id={popupId}
            role="tooltip"
            data-lines={lines > 1 ? 2 : 1}
            className={cn('tooltip-surface', 'focus-ring', className)}
          >
            {content}
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
