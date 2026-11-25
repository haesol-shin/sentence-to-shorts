import { cloneElement, useEffect, useId, useState, type ReactElement, type ReactNode } from 'react';
import { Tooltip as TooltipPrimitive } from '@base-ui/react/tooltip';

import { cn } from '@/shared/lib/utils';

import { usePopupContainer } from '../PopupContainer';
import { SentenceLines } from '../SentenceLines';

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
  /** A positioner class for a tooltip opened by a popup, above that popup. */
  positionerClassName?: string;
};

function existingDescriptionOf(element: ReactElement): string | undefined {
  const props: unknown = element.props;
  if (props === null || typeof props !== 'object' || !('aria-describedby' in props)) return undefined;
  const value = props['aria-describedby'];
  return typeof value === 'string' ? value : undefined;
}

/**
 * A short reason on hover and on keyboard focus. One line is a pill; two lines
 * or more use the content radius, both from the token set.
 */
export function Tooltip({ content, children, side = 'top', forceOpen, className, positionerClassName }: TooltipProps) {
  const container = usePopupContainer();
  const [open, setOpen] = useState(forceOpen ?? false);
  const [lines, setLines] = useState(1);
  const [popup, setPopup] = useState<HTMLDivElement | null>(null);
  const popupId = useId();
  const shown = forceOpen ?? open;
  const describedBy =
    [existingDescriptionOf(children), shown ? popupId : undefined].filter(Boolean).join(' ') || undefined;

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
        render={cloneElement(children, { 'aria-describedby': describedBy })}
      />
      <TooltipPrimitive.Portal container={container ?? undefined}>
        <TooltipPrimitive.Positioner
          side={side}
          sideOffset={8}
          collisionPadding={8}
          className={cn('tooltip-positioner', positionerClassName)}
        >
          <TooltipPrimitive.Popup
            ref={setPopup}
            id={popupId}
            role="tooltip"
            data-lines={lines > 1 ? 2 : 1}
            className={cn('tooltip-surface', 'focus-ring', className)}
          >
            <SentenceLines>{content}</SentenceLines>
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
