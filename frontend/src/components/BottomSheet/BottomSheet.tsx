import { useState, type ReactElement, type ReactNode } from 'react';
import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';

import { cn } from '@/shared/lib/utils';

import { PopupContainerContext } from '../PopupContainer';
import { SentenceLines } from '../SentenceLines';
import { useOverflowFade } from '../use-overflow-fade';

import './BottomSheet.css';

import { CloseButton } from '../CloseButton/CloseButton';

export type BottomSheetProps = {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  trigger?: ReactElement;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  label?: string;
  /** The name of the close control. A picking panel keeps its x. */
  closeLabel: string;
  className?: string;
};



/**
 * A panel that rises from the bottom. It is full width at 390 and 480 wide at
 * 1920. It closes with Escape, an outside press, or its close x.
 */
export function BottomSheet({
  title,
  description,
  children,
  actions,
  trigger,
  open,
  defaultOpen,
  onOpenChange,
  label,
  closeLabel,
  className,
}: BottomSheetProps) {
  const [popup, setPopup] = useState<HTMLDivElement | null>(null);
  const [scroll, setScroll] = useState<HTMLDivElement | null>(null);
  const fade = useOverflowFade(scroll, null);

  return (
    <DialogPrimitive.Root
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={(next) => onOpenChange?.(next)}
    >
      {trigger === undefined ? null : <DialogPrimitive.Trigger render={trigger} />}
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop className="sheet-backdrop" />
        <div className="sheet-positioner">
          <DialogPrimitive.Popup
            ref={setPopup}
            className={cn('sheet-popup', className)}
            role="dialog"
            aria-label={label}
          >
            <PopupContainerContext.Provider value={popup}>
              <div className="sheet-popup__head">
                <DialogPrimitive.Title className="sheet-popup__title">
                  {title}
                </DialogPrimitive.Title>
                <DialogPrimitive.Close render={<CloseButton label={closeLabel} />} />
              </div>
              <div
                className="sheet-popup__scroll-frame scroll-fade"
                data-fade={fade === 'none' ? undefined : fade}
              >
                <div className="sheet-popup__scroll" ref={setScroll}>
                  {description === undefined ? null : (
                    <DialogPrimitive.Description className="sheet-popup__description">
                      <SentenceLines>{description}</SentenceLines>
                    </DialogPrimitive.Description>
                  )}
                  {children === undefined ? null : (
                    <div className="sheet-popup__content">{children}</div>
                  )}
                </div>
              </div>
              {actions === undefined ? null : (
                <div className="sheet-popup__actions">{actions}</div>
              )}
            </PopupContainerContext.Provider>
          </DialogPrimitive.Popup>
        </div>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** Closes the sheet from an action control. Pass a control that forwards its ref. */
export const BottomSheetClose = DialogPrimitive.Close;
