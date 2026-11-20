import type { CaptionLayer, CaptionLayout, CatalogItem, ErrorItem } from '../api';
import type { SettingChange } from '../edit-context';
import type { Video } from '../model';

export const CAPTION_MODE_PATH = '/settings/caption/mode';
export const CAPTION_FONT_PATH = '/settings/caption/font_id';
export const CAPTION_POSITION_PATH = '/settings/caption/position';
export const CAPTION_EXTRA_PATH = '/settings/caption/extra';
export const TYPING_SOUND_PATH = '/settings/caption/typing_sound';

/** The fixed choices shown in the editor; the template determines which can be selected. */
export const CAPTION_MODES = ['sentence', 'phrase', 'typewriter'] as const;
export type CaptionMode = (typeof CAPTION_MODES)[number];

/** The five reviewed positions the contract names, from the top of the frame down. */
export const CAPTION_POSITIONS = ['top', 'upper', 'middle', 'lower', 'bottom'] as const;
export type CaptionPosition = (typeof CAPTION_POSITIONS)[number];

const DEFAULT_MODE: CaptionMode = 'sentence';
const DEFAULT_POSITION: CaptionPosition = 'bottom';
/** Where a new second layer starts: the top of the band, away from the default bottom caption. */
const DEFAULT_EXTRA_POSITION: CaptionPosition = 'top';

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

/** One caption line with the place the screen names it by. */
export interface LineRef {
  sceneId: string;
  lineId: string;
  sceneNumber: number;
  lineNumber: number;
  text: string;
}

export function lineRefs(video: Video | null): LineRef[] {
  if (video === null) return [];
  return video.scene_order.flatMap((sceneId, sceneIndex) =>
    (video.scenes[sceneId]?.lines ?? []).map((line, lineIndex) => ({
      sceneId,
      lineId: line.id,
      sceneNumber: sceneIndex + 1,
      lineNumber: lineIndex + 1,
      text: line.display_text,
    })),
  );
}

/** The second caption layer as the screen edits it, with the translation of every line. */
export interface ExtraDraft {
  language: string;
  mode: CaptionMode;
  fontId: string | null;
  position: CaptionPosition;
  /** The translation by line id. A line that has none reads as an empty text. */
  texts: Readonly<Record<string, string>>;
}

function savedTexts(video: Video, language: string): Record<string, string> {
  const texts: Record<string, string> = {};
  for (const ref of lineRefs(video)) {
    const line = video.scenes[ref.sceneId]?.lines.find((item) => item.id === ref.lineId);
    const found = line?.extra_texts?.find((item) => item.language === language);
    if (found !== undefined) texts[ref.lineId] = found.text;
  }
  return texts;
}

/** The saved second layer, or null when the video has none. */
export function savedDraft(video: Video | null): ExtraDraft | null {
  const layer: CaptionLayer | undefined = video?.settings.caption?.extra?.[0];
  if (video === null || layer === undefined) return null;
  const mode = layer.mode;
  const position = layer.position;
  return {
    language: layer.language,
    mode: CAPTION_MODES.includes(mode) ? mode : DEFAULT_MODE,
    fontId: layer.font_id.id,
    position: CAPTION_POSITIONS.includes(position) ? position : DEFAULT_EXTRA_POSITION,
    texts: savedTexts(video, layer.language),
  };
}

/** A new layer in a language: the first caption's font, the top position, and the translations already saved. */
export function startDraft(video: Video | null, language: string): ExtraDraft {
  return {
    language,
    mode: DEFAULT_MODE,
    fontId: readCaption(video).fontId,
    position: DEFAULT_EXTRA_POSITION,
    texts: video === null ? {} : savedTexts(video, language),
  };
}

/** Another language keeps the picked font, position and mode and reads that language's saved lines. */
export function changeLanguage(video: Video | null, draft: ExtraDraft, language: string): ExtraDraft {
  return { ...draft, language, texts: video === null ? {} : savedTexts(video, language) };
}

export function sameDraft(first: ExtraDraft | null, second: ExtraDraft | null): boolean {
  if (first === null || second === null) return first === second;
  const lines = new Set([...Object.keys(first.texts), ...Object.keys(second.texts)]);
  return (
    first.language === second.language &&
    first.mode === second.mode &&
    first.fontId === second.fontId &&
    first.position === second.position &&
    [...lines].every((id) => (first.texts[id] ?? '') === (second.texts[id] ?? ''))
  );
}

/** The lines whose translation is empty, in script order. */
export function missingLines(video: Video | null, draft: ExtraDraft): LineRef[] {
  return lineRefs(video).filter((ref) => (draft.texts[ref.lineId] ?? '').trim() === '');
}

/**
 * The changes that save the layer with every translation: the layer, then each
 * scene whose lines carry a different text. Null while the font is not one the catalog lists.
 */
export function extraChanges(
  video: Video,
  draft: ExtraDraft,
  fonts: readonly CatalogItem[],
): SettingChange[] | null {
  const font = fonts.find((item) => item.id === draft.fontId);
  if (font === undefined) return null;
  const layer: CaptionLayer = {
    language: draft.language,
    mode: draft.mode,
    font_id: { id: font.id, revision: font.revision },
    position: draft.position,
  };
  const changes: SettingChange[] = [{ path: CAPTION_EXTRA_PATH, value: [layer] }];
  for (const sceneId of video.scene_order) {
    const lines = video.scenes[sceneId]?.lines ?? [];
    const next = lines.map((line) => ({
      ...line,
      extra_texts: [{ language: draft.language, text: (draft.texts[line.id] ?? '').trim() }],
    }));
    const changed = lines.some(
      (line, index) =>
        JSON.stringify(line.extra_texts ?? []) !== JSON.stringify(next[index]?.extra_texts),
    );
    if (changed) changes.push({ path: `/scenes/${sceneId}/lines`, value: next });
  }
  return changes;
}

/** The font choices of one layer: the catalog fonts the style allows, plus the current one when it is not allowed. */
export function fontChoices(
  fonts: readonly CatalogItem[],
  allowed: readonly string[] | null,
  currentId: string | null,
  language: 'ko' | 'en',
): { value: string; label: string; disabled: boolean }[] {
  const items = fonts.map((font) => ({
    value: font.id,
    label: font.label[language],
    disabled: allowed?.includes(font.id) !== true,
  }));
  if (currentId !== null && !items.some((item) => item.value === currentId)) {
    items.unshift({ value: currentId, label: currentId, disabled: true });
  }
  return items;
}

/** Whether the server's layout says the two positions leave room; null while it has no answer. */
export function pairFits(
  layout: CaptionLayout | null,
  primary: CaptionPosition,
  extra: CaptionPosition,
): boolean | null {
  const pair = layout?.pairs.find((item) => item.primary === primary && item.extra === extra);
  return pair === undefined ? null : pair.fits;
}

export const CAPTION_ISSUE_CODES = [
  'caption_overlap',
  'caption_text_missing',
  'caption_mode_language',
  'caption_layer_unsupported',
] as const;
export type CaptionIssueCode = (typeof CAPTION_ISSUE_CODES)[number];

/** The layer a failed check belongs to: an overlap involves both layers, the other checks name the second. */
export type CaptionLayerName = 'primary' | 'extra' | 'both';

type LinePlace = Pick<LineRef, 'sceneNumber' | 'lineNumber'>;

export interface CaptionIssue {
  code: CaptionIssueCode;
  layer: CaptionLayerName;
  /** The lines the check names, in script order. */
  lines: readonly LinePlace[];
}

function issueCode(code: string): CaptionIssueCode | null {
  return CAPTION_ISSUE_CODES.find((item) => item === code) ?? null;
}

const LINE_POINTER = /^\/scenes\/([^/]+)\/lines\/(\d+)(?:\/|$)/u;

/** The caption checks among the failures a change was rejected with, one entry per check and layer. */
export function issuesFromErrors(errors: readonly ErrorItem[], video: Video | null): CaptionIssue[] {
  const found = new Map<CaptionIssueCode, LinePlace[]>();
  for (const error of errors) {
    const code = issueCode(error.code);
    if (code === null) continue;
    const lines = found.get(code) ?? [];
    found.set(code, lines);
    const match = LINE_POINTER.exec(error.pointer);
    const sceneIndex = match === null || video === null ? -1 : video.scene_order.indexOf(match[1]);
    if (match === null || sceneIndex < 0) continue;
    const place = { sceneNumber: sceneIndex + 1, lineNumber: Number(match[2]) + 1 };
    if (!lines.some((item) => item.sceneNumber === place.sceneNumber && item.lineNumber === place.lineNumber)) {
      lines.push(place);
    }
  }
  return [...found].map(([code, lines]) => ({
    code,
    layer: code === 'caption_overlap' ? 'both' : 'extra',
    lines,
  }));
}
