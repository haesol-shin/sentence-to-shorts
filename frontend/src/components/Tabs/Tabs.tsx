import type { ReactNode } from 'react';
import { Tabs as TabsPrimitive } from '@base-ui/react/tabs';

import { cn } from '@/shared/lib/utils';

import './Tabs.css';

export type ForceState = string | readonly string[];

export type TabItem = {
  value: string;
  label: ReactNode;
  disabled?: boolean;
};

export type TabsProps = {
  items: readonly TabItem[];
  /** The accessible name of the tab list. */
  label: string;
  defaultValue?: string;
  value?: string;
  onValueChange?: (value: string) => void;
  /** Forces a state on the first tab for the gallery. */
  forceState?: ForceState;
  className?: string;
};

function statesOf(value?: ForceState): readonly string[] {
  if (value === undefined) return [];
  return typeof value === 'string' ? value.split(/\s+/).filter(Boolean) : value;
}

/** A tab list. Arrow keys move and select, so no pointer is needed. */
export function Tabs({
  items,
  label,
  defaultValue,
  value,
  onValueChange,
  forceState,
  className,
}: TabsProps) {
  const forced = statesOf(forceState);
  const forcedAttr = forced.length > 0 ? forced.join(' ') : undefined;

  return (
    <TabsPrimitive.Root
      className={cn('tabs', className)}
      defaultValue={defaultValue}
      value={value}
      onValueChange={(next) => onValueChange?.(String(next))}
    >
      <TabsPrimitive.List className="tabs__list" aria-label={label}>
        {items.map((item, index) => (
          <TabsPrimitive.Tab
            key={item.value}
            value={item.value}
            disabled={item.disabled}
            className="tab hit-area focus-ring focus-ring--inset"
            data-force-state={index === 0 ? forcedAttr : undefined}
          >
            {item.label}
          </TabsPrimitive.Tab>
        ))}
      </TabsPrimitive.List>
    </TabsPrimitive.Root>
  );
}
