import type { ReactNode } from 'react';
import { Popover as PopoverPrimitive } from '@base-ui/react/popover';
import { AlertCircle, Check, ChevronDown, Info } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './TopBarStatus.css';

import { statesOf, type ForceState } from '../force-state';
import { LabelBox } from '../LabelBox';

export type TopBarStatusTone = 'idle' | 'saving' | 'saved' | 'error';

export type TopBarStatusProps = {
  /** The trigger label, for example "저장 실패". */
  label: string;
  tone?: TopBarStatusTone;
  /** The panel title and the accessible name of the panel. */
  title: string;
  description: ReactNode;
  /** Extra rows under the description, for example the last saved time. */
  detail?: ReactNode;
  /** The panel action row. */
  actions?: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  disabled?: boolean;
  /** Forces a trigger state for the gallery. */
  forceState?: ForceState;
  className?: string;
};

function toneIcon(tone: TopBarStatusTone): ReactNode {
  if (tone === 'error') return <AlertCircle aria-hidden="true" />;
  if (tone === 'saved') return <Check aria-hidden="true" />;
  if (tone === 'saving') return <span className="spinner" aria-hidden="true" />;
  return <Info aria-hidden="true" />;
}

/**
 * The status item at the right of the top bar. The trigger is a flat 44 high
 * item; the panel opens under it and keeps the token panel surface, shadow and
 * layer. Base UI owns Escape, the outside press and the focus return.
 */
export function TopBarStatus({
  label,
  tone = 'idle',
  title,
  description,
  detail,
  actions,
  open,
  defaultOpen,
  onOpenChange,
  disabled = false,
  forceState,
  className,
}: TopBarStatusProps) {
  const forced = statesOf(forceState);
  const isDisabled = disabled || forced.includes('disabled');

  return (
    <PopoverPrimitive.Root
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={(next) => onOpenChange?.(next)}
    >
      <PopoverPrimitive.Trigger
        className={cn('top-bar-status__trigger', 'hit-area', 'focus-ring', className)}
        data-tone={tone}
        data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
        disabled={isDisabled}
      >
        <span className="top-bar-status__icon" aria-hidden="true">
          {toneIcon(tone)}
        </span>
        <span className="top-bar-status__label">
          <LabelBox>{label}</LabelBox>
        </span>
        <span className="top-bar-status__chevron" aria-hidden="true">
          <ChevronDown />
        </span>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Positioner
          side="bottom"
          align="end"
          sideOffset={4}
          collisionPadding={8}
          className="status-positioner"
        >
          <PopoverPrimitive.Popup className="status-panel" role="dialog" aria-label={title}>
            <PopoverPrimitive.Title className="status-panel__title">{title}</PopoverPrimitive.Title>
            <PopoverPrimitive.Description className="status-panel__description">
              {description}
            </PopoverPrimitive.Description>
            {detail === undefined ? null : <div className="status-panel__detail">{detail}</div>}
            {actions === undefined ? null : <div className="status-panel__actions">{actions}</div>}
          </PopoverPrimitive.Popup>
        </PopoverPrimitive.Positioner>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
