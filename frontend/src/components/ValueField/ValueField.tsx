import { useId, useState, type ReactNode } from 'react';
import { Select as SelectPrimitive } from '@base-ui/react/select';
import { Check, ChevronDown } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './ValueField.css';

import { statesOf, type ForceState } from '../force-state';
import { usePopupContainer } from '../PopupContainer';
import { Tooltip } from '../Tooltip/Tooltip';
import { useOverflowFade } from '../use-overflow-fade';

export type ValueFieldItem<Value = string> = {
  /** Any value: a string, an index, a number, a boolean. Rows are matched with `Object.is`. */
  value: Value;
  label: string;
  disabled?: boolean;
  /** A Tag element from the caller. */
  tag?: ReactNode;
} & (
  | { unavailable?: false; unavailableName?: undefined }
  /** Dims the row and keeps the reason reachable through the visible note. */
  | { unavailable: true; unavailableName: string }
);

export type ValueFieldProps<Value = string> = {
  /** The accessible name of the field. */
  label: string;
  items: readonly ValueFieldItem<Value>[];
  placeholder?: string;
  /** The visible reason for unavailable rows. Without it the rows show no reason. */
  note?: ReactNode;
  /** The chosen value. `undefined` leaves the field uncontrolled; a value no row matches shows the placeholder. */
  value?: Value;
  defaultValue?: Value;
  onValueChange?: (value: Value) => void;
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
 * flips the open side only when the space below cannot hold the menu. The row
 * values can be of any type: the menu keys its rows by position and hands the
 * caller's own value back.
 */
export function ValueField<Value = string>({
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
}: ValueFieldProps<Value>) {
  const noteId = useId();
  const container = usePopupContainer();
  const [list, setList] = useState<HTMLDivElement | null>(null);
  const fade = useOverflowFade(list, '.field-item');
  const forced = statesOf(forceState);

  const resolvedNote = items.some((item) => item.unavailable) ? note : undefined;
  const rootItems = items.map((item, index) => ({ value: String(index), label: item.label }));
  // The menu keys rows by position, so a value of any type reaches Base UI as a string.
  const keyOf = (candidate: Value | undefined): string | null | undefined => {
    if (candidate === undefined) return undefined;
    const index = items.findIndex((item) => Object.is(item.value, candidate));
    return index < 0 ? null : String(index);
  };

  return (
    <SelectPrimitive.Root
      items={rootItems}
      value={keyOf(value)}
      defaultValue={keyOf(defaultValue) ?? undefined}
      onValueChange={(next) => {
        if (next === null) return;
        const item = items[Number(next)];
        if (item !== undefined) onValueChange?.(item.value);
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
                {items.map((item, index) => {
                  const key = String(index);
                  const row = (
                    <SelectPrimitive.Item
                      key={key}
                      value={key}
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
                      key={key}
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
