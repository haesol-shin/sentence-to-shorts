import type { ReactNode } from 'react';
import { Tabs as TabsPrimitive } from '@base-ui/react/tabs';

import { cn } from '@/shared/lib/utils';

import './Tabs.css';

import { statesOf, type ForceState } from '../force-state';
import { LabelBox } from '../LabelBox';

export type TabItem = {
  value: string;
  label: ReactNode;
  disabled?: boolean;
};

export type TabsProps = {
  items: readonly TabItem[];
  /** The accessible name of the tab list. */
  label: string;
  defaultValue?: string | null;
  value?: string | null;
  onValueChange?: (value: string) => void;
  /** Forces a state on the first tab for the gallery. */
  forceState?: ForceState;
  className?: string;
};



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
      onValueChange={(next) => {
        if (next !== null) onValueChange?.(String(next));
      }}
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
            <LabelBox>{item.label}</LabelBox>
          </TabsPrimitive.Tab>
        ))}
      </TabsPrimitive.List>
    </TabsPrimitive.Root>
  );
}
