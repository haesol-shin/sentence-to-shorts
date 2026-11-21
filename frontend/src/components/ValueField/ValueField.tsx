import { useId, useState, type ReactNode } from 'react';
import { Select as SelectPrimitive } from '@base-ui/react/select';
import { Check, ChevronDown } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './ValueField.css';

import { statesOf, type ForceState } from '../force-state';
import { usePopupContainer } from '../PopupContainer';
import { Tooltip } from '../Tooltip/Tooltip';
import { useOverflowFade } from '../use-overflow-fade';

export type ValueFieldItem = {
  value: string;
  label: string;
  disabled?: boolean;
  /** A Tag element from the caller. */
  tag?: ReactNode;
} & (
  | { unavailable?: false; unavailableName?: undefined }
  /** Dims the row and keeps the reason reachable through the visible note. */
  | { unavailable: true; unavailableName: string }
);

export type ValueFieldProps = {
  /** The accessible name of the field. */
  label: string;
  items: readonly ValueFieldItem[];
  placeholder?: string;
  /** The visible reason for unavailable rows. Without it the rows show no reason. */
  note?: ReactNode;
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  disabled?: boolean;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Forces a trigger state for the gallery. */
  forceState?: ForceState;
  className?: string;
};



/**
 * A grey value field whose menu opens below it with the same width. Base UI
 * flips the open side only when the space below cannot hold the menu.
 */
export function ValueField({
  label,
  items,
  placeholder,
  note,
  value,
  defaultValue,
  onValueChange,
  disabled = false,
  open,
  defaultOpen,
  onOpenChange,
  forceState,
  className,
}: ValueFieldProps) {
  const noteId = useId();
  const container = usePopupContainer();
  const [list, setList] = useState<HTMLDivElement | null>(null);
  const fade = useOverflowFade(list, '.field-item');
  const forced = statesOf(forceState);

  const resolvedNote = items.some((item) => item.unavailable) ? note : undefined;
  const rootItems = items.map((item) => ({ value: item.value, label: item.label }));

  return (
    <SelectPrimitive.Root
      items={rootItems}
      value={value}
      defaultValue={defaultValue}
      onValueChange={(next) => {
        if (next !== null) onValueChange?.(String(next));
      }}
      disabled={disabled}
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={(next) => onOpenChange?.(next)}
    >
      <SelectPrimitive.Trigger
        className={cn('field-trigger', 'hit-area', 'focus-ring', className)}
        aria-label={label}
        data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      >
        <SelectPrimitive.Value className="field-trigger__value" placeholder={placeholder} />
        <SelectPrimitive.Icon className="field-trigger__icon" render={<ChevronDown aria-hidden="true" />} />
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal container={container ?? undefined}>
        <SelectPrimitive.Positioner
          side="bottom"
          align="start"
          sideOffset={4}
          alignItemWithTrigger={false}
          collisionPadding={8}
          className="field-positioner"
        >
          <SelectPrimitive.Popup className="field-menu">
            <div className="scroll-fade" data-fade={fade === 'none' ? undefined : fade}>
              <SelectPrimitive.List className="field-menu__list" ref={setList}>
                {items.map((item) => {
                  const row = (
                    <SelectPrimitive.Item
                      key={item.value}
                      value={item.value}
                      disabled={item.disabled === true || item.unavailable === true}
                      className="field-item hit-area"
                      data-unavailable={item.unavailable === true ? '' : undefined}
                      aria-label={item.unavailable === true ? item.unavailableName : item.label}
                      aria-describedby={
                        item.unavailable === true && resolvedNote !== undefined ? noteId : undefined
                      }
                    >
                      <SelectPrimitive.ItemText className="field-item__text">{item.label}</SelectPrimitive.ItemText>
                      {item.tag === undefined ? null : <span className="field-item__tag">{item.tag}</span>}
                      <SelectPrimitive.ItemIndicator className="field-item__indicator">
                        <Check aria-hidden="true" />
                      </SelectPrimitive.ItemIndicator>
                    </SelectPrimitive.Item>
                  );
                  return item.unavailable === true && resolvedNote !== undefined ? (
                    <Tooltip
                      key={item.value}
                      content={resolvedNote}
                      side="right"
                      positionerClassName="tooltip-positioner--from-popup"
                    >
                      {row}
                    </Tooltip>
                  ) : (
                    row
                  );
                })}
              </SelectPrimitive.List>
            </div>
            {resolvedNote === undefined ? null : (
              <div className="field-note" id={noteId}>
                {resolvedNote}
              </div>
            )}
          </SelectPrimitive.Popup>
        </SelectPrimitive.Positioner>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
