import { useId, useRef, useState, type ReactNode } from 'react';
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
  /** A visible field name drawn inside the trigger, before the value. */
  name?: ReactNode;
  /** What the trigger shows for the chosen value; the menu rows keep their own labels. */
  display?: ReactNode;
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



/** The gap between the field, or the box holding it, and its menu. */
const MENU_GAP = 4;

/**
 * A grey value field whose menu opens below it with the same width. Base UI
 * flips the open side only when the space below cannot hold the menu. A field
 * inside an element marked `data-menu-below` keeps its menu clear of that
 * element on either side, so the menu never lies across the box that holds
 * the field. The row values can be of any type: the menu keys its rows by
 * position and hands the caller's own value back.
 */
export function ValueField<Value = string>({
  label,
  name,
  display,
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
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [hostGap, setHostGap] = useState({ below: 0, above: 0 });
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
      onOpenChange={(next) => {
        if (next) {
          const host = triggerRef.current?.closest('[data-menu-below]')?.getBoundingClientRect();
          const field = triggerRef.current?.getBoundingClientRect();
          setHostGap(
            host === undefined || field === undefined
              ? { below: 0, above: 0 }
              : { below: Math.max(0, host.bottom - field.bottom), above: Math.max(0, field.top - host.top) },
          );
        }
        onOpenChange?.(next);
      }}
    >
      <SelectPrimitive.Trigger
        ref={triggerRef}
        className={cn('field-trigger', 'hit-area', 'focus-ring', name !== undefined && 'field-trigger--named', className)}
        aria-label={label}
        data-force-state={forced.length > 0 ? forced.join(' ') : undefined}
      >
        {name === undefined ? null : <span className="field-trigger__name">{name}</span>}
        <SelectPrimitive.Value className="field-trigger__value" placeholder={placeholder}>
          {display === undefined ? undefined : () => display}
        </SelectPrimitive.Value>
        <SelectPrimitive.Icon className="field-trigger__icon" render={<ChevronDown aria-hidden="true" />} />
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal container={container ?? undefined}>
        <SelectPrimitive.Positioner
          side="bottom"
          align="start"
          sideOffset={({ side }) => MENU_GAP + (side === 'top' ? hostGap.above : hostGap.below)}
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
