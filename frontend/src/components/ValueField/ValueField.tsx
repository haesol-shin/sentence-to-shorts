import { useEffect, useId, useState, type ReactNode } from 'react';
import { Select as SelectPrimitive } from '@base-ui/react/select';
import { Check, ChevronDown } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './ValueField.css';

export type ForceState = string | readonly string[];

type Fade = 'none' | 'bottom' | 'both' | 'top';

export type ValueFieldItem = {
  value: string;
  label: string;
  disabled?: boolean;
  unavailable?: boolean;
  /** A Tag element from the caller. */
  tag?: ReactNode;
};

export type ValueFieldProps = {
  /** The accessible name of the field. */
  label: string;
  items: readonly ValueFieldItem[];
  placeholder?: string;
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

function statesOf(value?: ForceState): readonly string[] {
  if (value === undefined) return [];
  return typeof value === 'string' ? value.split(/\s+/).filter(Boolean) : value;
}

/**
 * A grey value field whose menu opens below it with the same width. Base UI
 * flips the open side only when the space below cannot hold the menu.
 */
export function ValueField({
  label,
  items,
  placeholder,
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
  const [list, setList] = useState<HTMLDivElement | null>(null);
  const [fade, setFade] = useState<Fade>('none');
  const forced = statesOf(forceState);

  useEffect(() => {
    if (list === null) return;
    const update = () => {
      if (list.scrollHeight <= list.clientHeight + 8) {
        list.style.maxHeight = '';
        setFade('none');
        return;
      }
      const items = list.querySelectorAll<HTMLElement>('.field-item');
      const pitch = items.length > 1 ? items[1].offsetTop - items[0].offsetTop : 0;
      const available = list.clientHeight;
      if (pitch > 0) {
        const snapped = Math.floor((available - pitch / 2) / pitch) * pitch + pitch / 2;
        if (snapped >= pitch && snapped < available) list.style.maxHeight = `${snapped}px`;
      }
      const atTop = list.scrollTop <= 1;
      const atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 1;
      setFade(atTop ? 'bottom' : atBottom ? 'top' : 'both');
    };
    update();
    list.addEventListener('scroll', update, { passive: true });
    if (typeof ResizeObserver === 'undefined') {
      return () => list.removeEventListener('scroll', update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(list);
    return () => {
      list.removeEventListener('scroll', update);
      observer.disconnect();
    };
  }, [list]);

  const resolvedNote = items.some((item) => item.unavailable)
    ? '곧 지원 항목은 다음 단계에서 열려요.'
    : undefined;
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
      <SelectPrimitive.Portal>
        <SelectPrimitive.Positioner
          side="bottom"
          align="start"
          sideOffset={4}
          alignItemWithTrigger={false}
          collisionPadding={8}
          className="field-positioner"
        >
          <SelectPrimitive.Popup className="field-menu" data-fade={fade === 'none' ? undefined : fade}>
            <div className="field-menu__body">
              <SelectPrimitive.List className="field-menu__list" ref={setList}>
                {items.map((item) => (
                  <SelectPrimitive.Item
                    key={item.value}
                    value={item.value}
                    disabled={item.disabled === true || item.unavailable === true}
                    className="field-item hit-area"
                    data-unavailable={item.unavailable === true ? '' : undefined}
                    aria-label={item.unavailable === true ? `${item.label} 곧 지원` : item.label}
                    aria-describedby={item.unavailable === true && resolvedNote !== undefined ? noteId : undefined}
                  >
                    <SelectPrimitive.ItemText className="field-item__text">{item.label}</SelectPrimitive.ItemText>
                    {item.tag === undefined ? null : <span className="field-item__tag">{item.tag}</span>}
                    <SelectPrimitive.ItemIndicator className="field-item__indicator">
                      <Check aria-hidden="true" />
                    </SelectPrimitive.ItemIndicator>
                  </SelectPrimitive.Item>
                ))}
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
