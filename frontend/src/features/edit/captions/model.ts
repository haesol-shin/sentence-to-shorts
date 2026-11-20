import type { SettingChange } from '../edit-context';
import type { Video } from '../model';

export const CAPTION_MODE_PATH = '/settings/caption/mode';
export const CAPTION_FONT_PATH = '/settings/caption/font_id';
export const CAPTION_POSITION_PATH = '/settings/caption/position';
export const TYPING_SOUND_PATH = '/settings/caption/typing_sound';

/** The fixed choices shown in the editor; the template determines which can be selected. */
export const CAPTION_MODES = ['sentence', 'phrase', 'typewriter'] as const;
export type CaptionMode = (typeof CAPTION_MODES)[number];

/** The five reviewed positions the contract names, from the top of the frame down. */
export const CAPTION_POSITIONS = ['top', 'upper', 'middle', 'lower', 'bottom'] as const;
export type CaptionPosition = (typeof CAPTION_POSITIONS)[number];

const DEFAULT_MODE: CaptionMode = 'sentence';
const DEFAULT_POSITION: CaptionPosition = 'bottom';

export interface CaptionView {
  mode: CaptionMode;
  fontId: string | null;
  position: CaptionPosition;
}

/** The caption values of a video. A value the video does not carry reads as its default. */
export function readCaption(video: Video | null): CaptionView {
  const caption = video?.settings.caption;
  const mode = caption?.mode;
  const position = caption?.position;
  const font = caption?.font_id;
  return {
    mode: mode !== undefined && CAPTION_MODES.includes(mode) ? mode : DEFAULT_MODE,
    fontId: typeof font?.id === 'string' && font.id !== '' ? font.id : null,
    position:
      position !== undefined && CAPTION_POSITIONS.includes(position) ? position : DEFAULT_POSITION,
  };
}

/** Leaving typewriter drops the typing sound in the same change, as the contract asks. */
export function modeChanges(video: Video | null, mode: CaptionMode): SettingChange[] {
  const changes: SettingChange[] = [{ path: CAPTION_MODE_PATH, value: mode }];
  const typingSound = video?.settings.caption?.typing_sound;
  if (mode !== 'typewriter' && typingSound !== undefined && typingSound !== null) {
    changes.push({ path: TYPING_SOUND_PATH, value: null });
  }
  return changes;
}
