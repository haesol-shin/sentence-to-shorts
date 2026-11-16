import type { ReactElement, ReactNode } from 'react';

import { Button } from '../Button/Button';
import { Dialog, DialogClose } from '../Dialog/Dialog';

export type ConfirmDialogProps = {
  title: ReactNode;
  children: ReactNode;
  confirmLabel: string;
  /** `null` removes the cancel action, for an acknowledgement only alert. */
  cancelLabel?: string | null;
  tone?: 'neutral' | 'danger';
  icon?: ReactNode;
  onConfirm?: () => void;
  trigger?: ReactElement;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};



/**
 * A question before a change lands. It uses the alert role, puts cancel first
 * and uses the primary action for the confirm. A danger tone colours the title
 * icon, not the action text, so the contrast on the grey cancel surface holds.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = '취소',
  tone = 'danger',
  icon,
  onConfirm,
  trigger,
  open,
  defaultOpen,
  onOpenChange,
}: ConfirmDialogProps) {
  return (
    <Dialog
      variant="alert"
      tone={tone}
      title={title}
      description={children}
      icon={icon}
      trigger={trigger}
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
      actions={
        <>
          {cancelLabel === null ? null : (
            <DialogClose render={<Button variant="secondary">{cancelLabel}</Button>} />
          )}
          <DialogClose
            render={
              <Button variant="primary" onClick={onConfirm}>
                {confirmLabel}
              </Button>
            }
          />
        </>
      }
    />
  );
}
