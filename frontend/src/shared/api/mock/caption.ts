import type { components } from '../generated/openapi';

type Video = components['schemas']['Video'];
type CaptionPosition = components['schemas']['CaptionPosition'];
type CaptionLayout = components['schemas']['CaptionLayout'];
type ErrorItem = components['schemas']['ErrorItem'];
type PinnedRef = components['schemas']['PinnedRef'];

/** The language catalog the server ships: id, Korean label, English label. */
export const MOCK_CAPTION_LANGUAGES: ReadonlyArray<readonly [string, string, string]> = [
  ['ko', '한국어', 'Korean'],
  ['en', '영어', 'English'],
];

const POSITIONS: readonly CaptionPosition[] = ['top', 'upper', 'middle', 'lower', 'bottom'];
const PIXEL_SIZE: Readonly<Record<string, number>> = { galmuri11: 11, galmuri14: 14 };
const DEFAULT_FONT = 'galmuri11';

/**
 * The position pairs the server's layout answers with `fits: true` for two
 * layers on the fixed stage, as recorded for the two bundled fonts. The key is
 * the larger of the two pixel sizes. Every other pair does not fit.
 */
const FITTING_PAIRS: Readonly<Record<number, readonly string[]>> = {
  11: [
    'top:lower', 'top:bottom', 'upper:lower', 'upper:bottom',
    'lower:top', 'lower:upper', 'bottom:top', 'bottom:upper',
  ],
  14: ['top:lower', 'top:bottom', 'upper:bottom', 'lower:top', 'bottom:top', 'bottom:upper'],
};

/** A template that draws its own caption box takes one caption layer. */
export function mockSingleLayer(layoutId: string | undefined): boolean {
  return layoutId === 'dialog_stage';
}

function pixelSize(fontId: string | undefined): number {
  return PIXEL_SIZE[fontId ?? DEFAULT_FONT] ?? PIXEL_SIZE[DEFAULT_FONT];
}

function fits(
  layoutId: string | undefined,
  primaryFont: string | undefined,
  primary: CaptionPosition,
  extraFont: string | undefined,
  extra: CaptionPosition,
): boolean {
  if (mockSingleLayer(layoutId)) return false;
  const size = Math.max(pixelSize(primaryFont), pixelSize(extraFont));
  return (FITTING_PAIRS[size] ?? []).includes(`${primary}:${extra}`);
}

/** The layout answer for the video's saved values, with the trial values laid over them. */
export function mockCaptionLayout(
  video: Video,
  query: { font: PinnedRef | null; extraLanguage: string | null; extraFont: PinnedRef | null },
): CaptionLayout {
  const caption = video.settings.caption;
  const saved = caption.extra?.[0];
  const primaryFont = query.font?.id ?? caption.font_id?.id;
  const language = query.extraLanguage ?? saved?.language ?? null;
  if (language === null) {
    return {
      primary_px: pixelSize(primaryFont) * 2,
      extra_px: null,
      pairs: POSITIONS.map((position) => ({ primary: position, extra: position, fits: true })),
    };
  }
  const extraFont = query.extraFont?.id ?? saved?.font_id?.id ?? primaryFont;
  const layoutId = video.settings.format.layout?.id;
  return {
    primary_px: pixelSize(primaryFont) * 2,
    extra_px: pixelSize(extraFont) * 2,
    pairs: POSITIONS.flatMap((primary) =>
      POSITIONS.map((extra) => ({
        primary,
        extra,
        fits: fits(layoutId, primaryFont, primary, extraFont, extra),
      })),
    ),
  };
}

/**
 * The caption checks the server runs on a saved video. A line without the
 * second language's text is reported, and so is a pair of positions that does
 * not fit; a line that lacks the text is not checked for position.
 */
export function mockCaptionIssues(video: Video): ErrorItem[] {
  const caption = video.settings.caption;
  const layer = caption.extra?.[0];
  if (layer === undefined) return [];
  const issues: ErrorItem[] = [];
  const pointer = '/settings/caption/extra/0';
  const layoutId = video.settings.format.layout?.id;
  const single = mockSingleLayer(layoutId);
  if (layer.mode !== 'sentence') issues.push({ code: 'caption_mode_language', pointer: `${pointer}/mode` });
  if (single) issues.push({ code: 'caption_layer_unsupported', pointer });
  const fitting = fits(layoutId, caption.font_id?.id, caption.position, layer.font_id?.id, layer.position);
  for (const sceneId of video.scene_order) {
    const lines = video.scenes[sceneId]?.lines ?? [];
    lines.forEach((line, index) => {
      const base = `/scenes/${sceneId}/lines/${index}`;
      if (!(line.extra_texts ?? []).some((item) => item.language === layer.language)) {
        issues.push({ code: 'caption_text_missing', pointer: `${base}/extra_texts` });
      } else if (!single && !fitting) {
        issues.push({ code: 'caption_overlap', pointer: base });
      }
    });
  }
  return issues;
}
