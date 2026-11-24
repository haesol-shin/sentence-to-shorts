export const CARD_WIDTH = 216;
export const CARD_GAP = 12;
export const CARD_ROWS = 2;
export const CARD_TITLE_LIMIT = 24;
export const CARD_DESCRIPTION_LIMIT = 36;

/** The cards a row can hold at this width. Each card keeps its 216px width. */
export function cardColumns(width: number): number {
  return Math.max(1, Math.floor((width + CARD_GAP) / (CARD_WIDTH + CARD_GAP)));
}

/** Two rows stay visible; the rest open from 「더 보기」. */
export function visibleCardCount(total: number, columns: number): number {
  return Math.min(total, Math.max(1, columns) * CARD_ROWS);
}

/** The data side gives every card text that fits its two reserved lines. */
export function clampCardText(text: string, limit = CARD_TITLE_LIMIT): string {
  const characters = Array.from(text.trim());
  if (characters.length <= limit) return characters.join('');
  return `${characters.slice(0, limit - 1).join('')}…`;
}

/**
 * The order the three story cards read in, for the first screen and the concept
 * screen alike: one list, so the two screens cannot drift apart.
 */
export const STORY_CARD_ORDER: readonly string[] = ['just_three', 'what_if', 'its_like'];
