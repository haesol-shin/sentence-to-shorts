import { useId, useState, type ReactElement, type ReactNode } from 'react';
import { Menu as MenuPrimitive } from '@base-ui/react/menu';
import { Check } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './MenuButton.css';

import { statesOf, type ForceState } from '../force-state';
import { Tooltip } from '../Tooltip/Tooltip';
import { useOverflowFade } from '../use-overflow-fade';

export type MenuItemSpec = {
  value: string;
  label: ReactNode;
  disabled?: boolean;
  selected?: boolean;
  /** Dims the row and keeps the reason reachable through the visible note. */
  unavailable?: boolean;
  /** A Tag element from the caller. One tag component serves every surface. */
  tag?: ReactNode;
};

export type MenuButtonProps = {
  /** A control that forwards its ref and opens this menu. Compose a Button. */
  trigger: ReactElement;
  /** The accessible name of the menu surface. */
  label: string;
  heading?: ReactNode;
  items: readonly MenuItemSpec[];
  /** A visible reason for unavailable rows. A default notes the next step. */
  note?: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  onSelect?: (value: string) => void;
  /** Forces a state on one row for the gallery. */
  forceItemValue?: string;
  forceItemState?: ForceState;
  className?: string;
};



/**
 * A dropdown menu. The trigger and the unavailable tag are composed by the
 * caller; the unavailable reason uses the shared tooltip part.
 */
export function MenuButton({
  trigger,
  label,
  heading,
  items,
  note,
  open,
  defaultOpen,
  onOpenChange,
  onSelect,
  forceItemValue,
  forceItemState,
  className,
}: MenuButtonProps) {
  const noteId = useId();
  const [list, setList] = useState<HTMLDivElement | null>(null);
  const fade = useOverflowFade(list, '.menu-item');
  const forced = statesOf(forceItemState);
  const forcedAttr = forced.length > 0 ? forced.join(' ') : undefined;
  const resolvedNote =
    note ?? (items.some((item) => item.unavailable) ? '곧 지원 항목은 다음 단계에서 열려요.' : undefined);

  const rows = items.map((item) => {
    const forcedItem = item.value === (forceItemValue ?? items[0]?.value);
    const row = (
      <MenuPrimitive.Item
        key={item.value}
        className="menu-item hit-area focus-ring focus-ring--inset"
        disabled={item.disabled === true || item.unavailable === true}
        data-selected={item.selected === true ? '' : undefined}
        data-unavailable={item.unavailable === true ? '' : undefined}
        data-force-state={forcedItem ? forcedAttr : undefined}
        aria-label={item.unavailable === true ? `${String(item.label)} 곧 지원` : undefined}
        aria-describedby={item.unavailable === true && resolvedNote !== undefined ? noteId : undefined}
        onClick={() => onSelect?.(item.value)}
      >
        <span className="menu-item__label">{item.label}</span>
        {item.tag === undefined ? null : <span className="menu-item__tag">{item.tag}</span>}
        {item.selected === true ? <Check className="menu-item__check" aria-hidden="true" /> : null}
      </MenuPrimitive.Item>
    );
    return item.unavailable === true && resolvedNote !== undefined ? (
      <Tooltip key={item.value} content={resolvedNote} side="right">
        {row}
      </Tooltip>
    ) : (
      row
    );
  });

  return (
    <MenuPrimitive.Root open={open} defaultOpen={defaultOpen} onOpenChange={(next) => onOpenChange?.(next)}>
      <MenuPrimitive.Trigger render={trigger} />
      <MenuPrimitive.Portal>
        <MenuPrimitive.Positioner
          side="bottom"
          align="start"
          sideOffset={4}
          collisionPadding={8}
          className="menu-positioner"
        >
          <MenuPrimitive.Popup
            className={cn('menu-surface', className)}
            aria-label={label}
            data-fade={fade === 'none' ? undefined : fade}
          >
            <div className="menu-body">
              <div className="menu-scroll" ref={setList}>
                {heading === undefined ? (
                  rows
                ) : (
                  <MenuPrimitive.Group>
                    <MenuPrimitive.GroupLabel className="menu-label">{heading}</MenuPrimitive.GroupLabel>
                    {rows}
                  </MenuPrimitive.Group>
                )}
              </div>
            </div>
            {resolvedNote === undefined ? null : (
              <div className="menu-note" id={noteId}>
                {resolvedNote}
              </div>
            )}
          </MenuPrimitive.Popup>
        </MenuPrimitive.Positioner>
      </MenuPrimitive.Portal>
    </MenuPrimitive.Root>
  );
}
