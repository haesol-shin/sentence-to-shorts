import { useState, type DragEvent } from 'react';
import { ChevronDown, ChevronUp, GripVertical } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import './ReorderList.css';

import { statesOf, type ForceState } from '../force-state';
import { LabelBox } from '../LabelBox';

export type ReorderItem = {
  id: string;
  label: string;
};

export type ReorderListProps = {
  /** The accessible name of the list. */
  label: string;
  items: readonly ReorderItem[];
  /** Accessible names of the visual-only controls; each gets the row label. */
  labels: {
    grip: (item: string) => string;
    up: (item: string) => string;
    down: (item: string) => string;
  };
  onReorder?: (items: readonly ReorderItem[]) => void;
  /** Forces a row state for the gallery. */
  forceState?: ForceState;
  /** Shows that forced state on one row only. */
  forceItem?: string;
  className?: string;
};

/**
 * A list whose rows move by a grip drag or by the up and down controls. The
 * row keeps 44 height. The grip is 32 wide and the move controls are 36; the
 * shared transparent ring fills each to 44 and the 12 gaps keep the rings from
 * touching.
 */
export function ReorderList({
  label,
  items,
  labels,
  onReorder,
  forceState,
  forceItem,
  className,
}: ReorderListProps) {
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  const forced = statesOf(forceState);
  const forcedAttr = forced.length > 0 ? forced.join(' ') : undefined;

  const move = (from: number, to: number) => {
    if (to < 0 || to >= items.length || from === to) return;
    const next = [...items];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    onReorder?.(next);
  };

  const dropOn = (event: DragEvent<HTMLLIElement>, index: number) => {
    event.preventDefault();
    if (draggingIndex !== null) move(draggingIndex, index);
    setDraggingIndex(null);
  };

  return (
    <ul className={cn('reorder-list', className)} aria-label={label}>
      {items.map((item, index) => (
        <li
          key={item.id}
          className="reorder-row"
          data-row-state={draggingIndex === index ? 'dragging' : undefined}
          data-force-state={
            forceItem === undefined || forceItem === item.id ? forcedAttr : undefined
          }
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => dropOn(event, index)}
        >
          <button
            type="button"
            className="reorder-row__grip hit-area focus-ring"
            aria-label={labels.grip(item.label)}
            draggable
            data-force-state={
              forceItem === undefined || forceItem === item.id ? forcedAttr : undefined
            }
            onDragStart={(event) => {
              event.dataTransfer.effectAllowed = 'move';
              event.dataTransfer.setData('text/plain', item.id);
              setDraggingIndex(index);
            }}
            onDragEnd={() => setDraggingIndex(null)}
          >
            <GripVertical aria-hidden="true" />
          </button>
          <span className="reorder-row__label">
            <LabelBox>{item.label}</LabelBox>
          </span>
          <span className="reorder-row__moves">
            <button
              type="button"
              className="reorder-row__move hit-area focus-ring"
              aria-label={labels.up(item.label)}
              disabled={index === 0}
              onClick={() => move(index, index - 1)}
            >
              <ChevronUp aria-hidden="true" />
            </button>
            <button
              type="button"
              className="reorder-row__move hit-area focus-ring"
              aria-label={labels.down(item.label)}
              disabled={index === items.length - 1}
              onClick={() => move(index, index + 1)}
            >
              <ChevronDown aria-hidden="true" />
            </button>
          </span>
        </li>
      ))}
    </ul>
  );
}
