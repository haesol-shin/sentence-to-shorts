import { cardIdForSettings, originOf } from './model';
import { valueLabel } from './labels';

import type { Settings } from './types';

type Translate = (key: string, vars?: Record<string, string | number>) => string;

/**
 * The particle a value takes before 「골랐어요」. A Hangul syllable with a final
 * consonant takes 으로; a value ending in anything else reads as 으로 too,
 * which covers the story labels that end in a question mark.
 */
function roParticle(value: string): string {
  const last = Array.from(value.trim()).at(-1) ?? '';
  const code = last.codePointAt(0) ?? 0;
  const hangul = code >= 0xac00 && code <= 0xd7a3;
  if (!hangul) return '으로';
  return (code - 0xac00) % 28 === 0 ? '로' : '으로';
}

/**
 * The first conversation reply on the concept step, naming the values the
 * draft settled. `settings` is the opening snapshot, so later edits do not
 * rewrite what the app said it picked.
 */
export function conceptGreeting(settings: Settings, t: Translate): string {
  const cardId = cardIdForSettings(settings);
  const story = cardId === null
    ? valueLabel(settings.format.story_structure, t)
    : t(`concept.card.${cardId}`);
  const length = valueLabel(settings.target_duration_s, t);
  const scenes = t('concept.head.sceneCountValue', { count: settings.format.scene_count });
  const lines = [
    t('shell.conversation.conceptStory', { value: story, particle: roParticle(story) }),
    t('shell.conversation.conceptLength', { length, scenes }),
  ];

  const style = valueLabel(settings.visual.art_style, t);
  const character = valueLabel(settings.visual.character?.slots.body, t);
  const stylePicked = originOf(settings, '/visual/art_style') !== 'default';
  const characterPicked = originOf(settings, '/visual/character') !== 'default';
  if (stylePicked) {
    lines.push(t('shell.conversation.conceptStyle', { value: style, particle: roParticle(style) }));
  }
  if (characterPicked) {
    lines.push(t('shell.conversation.conceptCharacter', { value: character, particle: roParticle(character) }));
  }
  if (!stylePicked && !characterPicked) {
    lines.push(t('shell.conversation.conceptDefaultBoth', {
      first: t('concept.style'),
      second: t('concept.character'),
    }));
  } else if (!stylePicked) {
    lines.push(t('shell.conversation.conceptDefaultOne', { name: t('concept.style') }));
  } else if (!characterPicked) {
    lines.push(t('shell.conversation.conceptDefaultOne', { name: t('concept.character') }));
  }
  lines.push(t('shell.conversation.conceptAsk'));
  return lines.join(' ');
}
