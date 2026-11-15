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

/** Screens that also show the four step indicator (SPEC 10a.2: edit only). */
export const STAGE_INDICATOR_SCREENS: readonly Stage[] = ['edit'];

export function showsStageIndicator(view: View): boolean {
  return STAGE_INDICATOR_SCREENS.some((stage) => stage === view);
}


export const DEFAULT_LANGUAGE: Language = 'ko';
