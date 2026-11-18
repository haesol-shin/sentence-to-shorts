import { useState, type ReactElement, type ReactNode } from 'react';
import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { cn } from '@/shared/lib/utils';

import { PopupContainerContext } from '../PopupContainer';
import { useOverflowFade } from '../use-overflow-fade';

import './Dialog.css';

export type DialogVariant = 'dialog' | 'alert';

export type DialogTone = 'neutral' | 'warning' | 'danger';

export type DialogProps = {
  title: ReactNode;
  /** The leading sentence under the title. */
  description?: ReactNode;
  /** Extra window content, for example change rows or a notice. */
  children?: ReactNode;
  /** The action row. Put the cancel control first so an alert opens on it. */
  actions?: ReactNode;
  variant?: DialogVariant;
  tone?: DialogTone;
  icon?: ReactNode;
  /** A control that forwards its ref and opens this window. */
  trigger?: ReactElement;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** The accessible name when the visible title is not enough. */
  label?: string;
  className?: string;
};



/**
 * One window for confirmations and alerts. It is 480 wide, uses 24 radius and
 * 24 padding, and draws the dark dialog scrim behind it. Escape closes it and
 * focus returns to its trigger.
 */
export function Dialog({
  title,
  description,
  children,
  actions,
  variant = 'dialog',
  tone = 'neutral',
  icon,
  trigger,
  open,
  defaultOpen,
  onOpenChange,
  label,
  className,
}: DialogProps) {
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
        <DialogPrimitive.Backdrop className="dialog-backdrop" />
        <div className="dialog-positioner">
          <DialogPrimitive.Popup
            ref={setPopup}
            className={cn('dialog', className)}
            data-tone={tone}
            role={variant === 'alert' ? 'alertdialog' : 'dialog'}
            aria-label={label}
          >
            <PopupContainerContext.Provider value={popup}>
              <div
                className="dialog__scroll-frame scroll-fade"
                data-fade={fade === 'none' ? undefined : fade}
              >
                <div className="dialog__scroll" ref={setScroll}>
                  <DialogPrimitive.Title className="dialog__title">
                    {icon === undefined ? null : (
                      <span className="dialog__icon" aria-hidden="true">
                        {icon}
                      </span>
                    )}
                    {title}
                  </DialogPrimitive.Title>
                  {description === undefined ? null : (
                    <DialogPrimitive.Description className="dialog__description">
                      {description}
                    </DialogPrimitive.Description>
                  )}
                  {children === undefined ? null : <div className="dialog__content">{children}</div>}
                </div>
              </div>
              {actions === undefined ? null : <div className="dialog__actions">{actions}</div>}
            </PopupContainerContext.Provider>
          </DialogPrimitive.Popup>
        </div>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** Closes the window from an action control. Pass a control that forwards its ref. */
export const DialogClose = DialogPrimitive.Close;
