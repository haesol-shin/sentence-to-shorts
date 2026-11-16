import type { ReactElement, ReactNode } from 'react';
import { ArrowRight, RefreshCw } from 'lucide-react';

import './RangeDialog.css';

import { Button } from '../Button/Button';
import { Dialog, DialogClose } from '../Dialog/Dialog';

export type RangeChange = {
  label: string;
  before: ReactNode;
  after: ReactNode;
};

export type RangeDialogProps = {
  title?: string;
  /** The sentence that explains why this change needs confirmation. */
  intro: string;
  changes: readonly RangeChange[];
  /** The parts that will be built again, one line each. */
  scope: readonly string[];
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm?: () => void;
  trigger?: ReactElement;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};



/**
 * The SPEC 8a confirmation. It shows the values that change and the range that
 * is rebuilt before a script, several scenes, a fixed value or a render change
 * lands. A single value change never opens it.
 */
export function RangeDialog({
  title = '다시 만들 범위를 확인해 주세요',
  intro,
  changes,
  scope,
  confirmLabel,
  cancelLabel = '취소',
  onConfirm,
  trigger,
  open,
  defaultOpen,
  onOpenChange,
}: RangeDialogProps) {
  return (
    <Dialog
      variant="alert"
      title={title}
      description={intro}
      icon={<RefreshCw />}
      trigger={trigger}
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
      actions={
        <>
          <DialogClose render={<Button variant="secondary">{cancelLabel}</Button>} />
          <DialogClose
            render={
              <Button variant="primary" onClick={onConfirm}>
                {confirmLabel}
              </Button>
            }
          />
        </>
      }
    >
      {changes.length === 0 ? null : (
        <dl className="range-dialog__changes">
          {changes.map((change) => (
            <div className="range-dialog__row" key={change.label}>
              <dt className="range-dialog__label">{change.label}</dt>
              <dd className="range-dialog__values">
                <span className="range-dialog__before">{change.before}</span>
                <ArrowRight className="range-dialog__arrow" aria-hidden="true" />
                <span className="range-dialog__after">{change.after}</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
      {scope.length === 0 ? null : (
        <div className="range-dialog__scope">
          <p className="range-dialog__scope-title">다시 만드는 범위</p>
          <ul className="range-dialog__scope-list">
            {scope.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
    </Dialog>
  );
}
