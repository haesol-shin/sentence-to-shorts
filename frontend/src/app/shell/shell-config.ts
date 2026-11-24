import type { Language } from '@/shared/api/client';

export type View = 'first' | 'concept' | 'script' | 'edit' | 'export';
export type Stage = Exclude<View, 'first'>;

export interface CardPick {
  id: string;
  label: string;
}

/**
 * One switch for the sidebar names: `tooltip` keeps the rail collapsed and
 * shows a name on hover or focus, `inline` draws the name beside the icon.
 */
export const NAV_LABEL_MODE: 'tooltip' | 'inline' = 'tooltip';

/** Flow order of the four steps. */
export const STAGES: readonly Stage[] = ['concept', 'script', 'edit', 'export'];

/**
 * The steps the top bar draws as tabs on every stage screen. Export is not a
 * tab: it opens from the edit step, so the edit tab stays current there.
 */
export const STEP_TABS: readonly Stage[] = ['concept', 'script', 'edit'];

export function stepTabOf(stage: Stage): Stage {
  return stage === 'export' ? 'edit' : stage;
}


export const DEFAULT_LANGUAGE: Language = 'ko';
