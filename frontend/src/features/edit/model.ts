import type { components } from '@/shared/api/generated/openapi';
import type { Translate } from '@/shared/lib/i18n/locale';

export type Video = components['schemas']['Video'];
export type VideoView = components['schemas']['VideoView'];
export type VideoBuild = components['schemas']['VideoBuild'];
export type Scene = components['schemas']['Scene'];
export type Line = components['schemas']['Line'];
export type Span = components['schemas']['Span'];
export type SfxCue = components['schemas']['SfxCue'];
export type ArtifactStatus = components['schemas']['ArtifactStatus'];
export type PlacementAnchor = components['schemas']['PlacementAnchor'];

export interface PositionChoice {
  anchor: PlacementAnchor;
  labelKey: string;
}

/** The canon line count a scene may reach before adding another line stops. */
export const MAX_LINES_PER_SCENE = 4;

/**
 * The nine places of the position menu, top row first. The bottom row keeps
 * the old unprefixed anchors, so saved scenes keep their place.
 */
export const POSITION_CHOICES: readonly PositionChoice[] = [
  { anchor: 'top_left', labelKey: 'edit.position.topLeft' },
  { anchor: 'top_center', labelKey: 'edit.position.topCenter' },
  { anchor: 'top_right', labelKey: 'edit.position.topRight' },
  { anchor: 'middle_left', labelKey: 'edit.position.middleLeft' },
  { anchor: 'middle_center', labelKey: 'edit.position.middleCenter' },
  { anchor: 'middle_right', labelKey: 'edit.position.middleRight' },
  { anchor: 'left', labelKey: 'edit.position.bottomLeft' },
  { anchor: 'center', labelKey: 'edit.position.bottomCenter' },
  { anchor: 'right', labelKey: 'edit.position.bottomRight' },
] as const;

/** Keep option names identical in the scene form and change review. */
export function sceneVisualLabel(
  t: Translate,
  field: 'background' | 'expression' | 'position' | 'sfx',
  value: unknown,
  catalog: readonly string[] = [],
): string {
  if (value == null || value === '') return t('edit.change.none');
  const key = field === 'position'
    ? POSITION_CHOICES.find((choice) => choice.anchor === value)?.labelKey
    : `edit.${field === 'sfx' ? 'sfx.name' : field}.${String(value)}`;
  if (key !== undefined) {
    const label = t(key);
    if (label !== key) return label;
  }
  const index = typeof value === 'string' ? catalog.indexOf(value) : -1;
  if (index >= 0) return t('edit.scene.unknownOption', { number: index + 1 });
  if (typeof value !== 'string') return t('audio.review.unknown');
  return t('edit.scene.unlistedOption', { id: value });
}

export function scenesOf(video: Video | null): Scene[] {
  if (video === null) return [];
  return video.scene_order
    .map((id) => video.scenes[id])
    .filter((scene): scene is Scene => scene !== undefined);
}

export function sceneNumber(video: Video | null, sceneId: string | null): number {
  if (video === null || sceneId === null) return 0;
  return video.scene_order.indexOf(sceneId) + 1;
}

/** A scene whose still is stale or missing is never drawn as a finished picture. */
export function stillIsReady(build: VideoBuild | null, sceneId: string): boolean {
  const still = build?.scenes[sceneId]?.still;
  return still?.state === 'fresh' && still.artifact !== null;
}

export function stillState(
  build: VideoBuild | null,
  sceneId: string,
): ArtifactStatus['state'] {
  return build?.scenes[sceneId]?.still.state ?? 'missing';
}

/**
 * A deterministic reading estimate for one scene. The build view carries only
 * the whole-video estimate, so the scene chip uses the spoken text length at a
 * calm Korean narration pace of about five characters per second.
 */
export function estimatedSeconds(scene: Scene | null): number {
  if (scene === null) return 0;
  const characters = scene.lines.reduce((total, line) => total + line.speech_text.length, 0);
  return Math.max(3, Math.round(characters / 5.2));
}

export function totalEstimatedSeconds(scenes: readonly Scene[]): number {
  return scenes.reduce((total, scene) => total + estimatedSeconds(scene), 0);
}

export type BandField = 'background' | 'expression' | 'position' | 'lines' | 'highlight' | 'sfx';

/** What a change touched in one scene, so the scene form lights exactly those cells. */
export function changedFields(before: Scene | undefined, after: Scene | undefined): BandField[] {
  if (before === undefined || after === undefined) return [];
  const fields: BandField[] = [];
  const character = (scene: Scene) => scene.visual?.characters?.[0];
  if ((before.visual?.background_id ?? '') !== (after.visual?.background_id ?? '')) fields.push('background');
  if ((character(before)?.expression_id ?? '') !== (character(after)?.expression_id ?? '')) fields.push('expression');
  if ((character(before)?.anchor ?? '') !== (character(after)?.anchor ?? '')) fields.push('position');
  const texts = (scene: Scene) => JSON.stringify(scene.lines.map((line) => [line.id, line.display_text]));
  if (texts(before) !== texts(after)) fields.push('lines');
  const spans = (scene: Scene) => JSON.stringify(scene.lines.map((line) => line.highlight));
  if (spans(before) !== spans(after)) fields.push('highlight');
  const cues = (scene: Scene) => JSON.stringify(scene.visual?.sfx ?? []);
  if (cues(before) !== cues(after)) fields.push('sfx');
  return fields;
}

export function moveScene(
  order: readonly string[],
  sceneId: string,
  toIndex: number,
): string[] {
  const from = order.indexOf(sceneId);
  if (from < 0) return [...order];
  const next = [...order];
  const [moved] = next.splice(from, 1);
  if (moved === undefined) return [...order];
  const bounded = Math.max(0, Math.min(toIndex, next.length));
  next.splice(bounded, 0, moved);
  return next;
}

/**
 * A numbered story keeps its count order; moving the hook away or putting a
 * numbered beat before its predecessor breaks the flow the viewer reads.
 */
/**
 * The hook stays first and numbered beats keep their original relative order.
 * A swap of two numbered beats reverses that order even when no label repeats.
 */
export function breaksFlow(video: Video, order: readonly string[]): boolean {
  if (order.length === 0) return false;
  const originalFirst = video.scenes[video.scene_order[0] ?? ''];
  if (originalFirst?.beat_id === 'hook' && order[0] !== video.scene_order[0]) return true;
  const numbered = (ids: readonly string[]) =>
    ids
      .map((id) => video.scenes[id])
      .filter((scene): scene is Scene => scene !== undefined)
      .filter((scene) => /^\d|first|second|third|fourth|fifth/u.test(scene.beat_id))
      .map((scene) => scene.beat_id);
  const original = numbered(video.scene_order);
  const proposed = numbered(order);
  return proposed.some((beat, index) => original[index] !== beat);
}

export interface SceneFieldPatch {
  kind: 'background' | 'expression' | 'position' | 'highlight' | 'sfx';
  value?: string;
  expressionId?: string;
  anchor?: PlacementAnchor;
  lineId?: string;
  spans?: Span[];
  cues?: SfxCue[];
}

export interface ScenePatch {
  backgroundId?: string;
  expressionId?: string;
  anchor?: PlacementAnchor;
  highlights?: Record<string, Span[]>;
  sfx?: SfxCue[];
}

export function applyScenePatch(video: Video, sceneId: string, patch: ScenePatch): Video {
  const scene = video.scenes[sceneId];
  if (scene === undefined) return video;
  const visual = scene.visual ?? {
    background_id: 'bg_village',
    characters: [],
    elements: [],
    sfx: [],
    transition_in: 'cut' as const,
  };
  const characters =
    patch.expressionId === undefined && patch.anchor === undefined
      ? visual.characters
      : [
          {
            anchor: patch.anchor ?? visual.characters[0]?.anchor ?? 'center',
            expression_id: patch.expressionId ?? visual.characters[0]?.expression_id ?? 'expr_neutral',
            pose_id: visual.characters[0]?.pose_id ?? 'pose_idle',
            motion: visual.characters[0]?.motion ?? 'none',
          },
        ];
  const lines =
    patch.highlights === undefined
      ? scene.lines
      : scene.lines.map((line) =>
          patch.highlights?.[line.id] === undefined
            ? line
            : { ...line, highlight: patch.highlights[line.id] ?? [] },
        );
  return {
    ...video,
    scenes: {
      ...video.scenes,
      [sceneId]: {
        ...scene,
        lines,
        visual: {
          ...visual,
          background_id: patch.backgroundId ?? visual.background_id,
          characters,
          sfx: patch.sfx ?? visual.sfx,
        },
      },
    },
  };
}

const ID_ALPHABET = '0123456789abcdefghjkmnpqrstvwxyz';

/** The contract id shape: prefix, one digit and 26 Crockford-like characters. */
export function newLocalId(prefix: 's' | 'l'): string {
  const bytes = new Uint8Array(26);
  globalThis.crypto?.getRandomValues(bytes);
  const tail = Array.from(bytes, (byte) => ID_ALPHABET[byte % ID_ALPHABET.length]).join('');
  return `${prefix}_0${tail.slice(0, 25)}`;
}

export function duplicateScene(video: Video, sceneId: string, newSceneId: string): Scene | null {
  const source = video.scenes[sceneId];
  if (source === undefined) return null;
  const lineIds = new Map(source.lines.map((line) => [line.id, newLocalId('l')]));
  const mapLine = (id: string | null): string | null =>
    id === null ? null : lineIds.get(id) ?? id;
  return {
    ...source,
    id: newSceneId,
    lines: source.lines.map((line) => ({
      ...line,
      id: lineIds.get(line.id) ?? newLocalId('l'),
    })),
    visual:
      source.visual === null
        ? null
        : {
            ...source.visual,
            characters: source.visual.characters.map((character) => ({ ...character })),
            elements: source.visual.elements.map((element) => ({
              ...element,
              reveal_line_id: mapLine(element.reveal_line_id),
            })),
            sfx: source.visual.sfx.map((cue) => ({
              ...cue,
              line_id: mapLine(cue.line_id) ?? cue.line_id,
            })),
          },
  };
}

export function insertScene(
  video: Video,
  afterId: string,
  scene: Scene,
): { video: Video; order: string[] } {
  const index = video.scene_order.indexOf(afterId);
  const order = [...video.scene_order];
  order.splice(index < 0 ? order.length : index + 1, 0, scene.id);
  return {
    video: { ...video, scene_order: order, scenes: { ...video.scenes, [scene.id]: scene } },
    order,
  };
}

export function removeScene(video: Video, sceneId: string): { video: Video; order: string[] } {
  const order = video.scene_order.filter((id) => id !== sceneId);
  const scenes = { ...video.scenes };
  delete scenes[sceneId];
  return { video: { ...video, scene_order: order, scenes }, order };
}

export function withOrder(video: Video, order: readonly string[]): Video {
  return { ...video, scene_order: [...order] };
}

/**
 * The words a rewrite drops can still sit in the scene before or after it.
 * The app only warns; it never edits a neighbour.
 */
export function adjacentEchoes(
  video: Video,
  sceneId: string,
  oldText: string,
  newText: string,
): string[] {
  const dropped = oldText
    .split(/\s+/u)
    .map((word) => word.replace(/[^\p{L}\p{N}]/gu, ''))
    .filter((word) => word.length >= 2 && !newText.includes(word));
  if (dropped.length === 0) return [];
  const index = video.scene_order.indexOf(sceneId);
  return [index - 1, index + 1]
    .map((position) => video.scene_order[position])
    .filter((id): id is string => id !== undefined)
    .filter((id) => {
      const scene = video.scenes[id];
      if (scene === undefined) return false;
      const text = scene.lines.map((line) => line.display_text).join(' ');
      return dropped.some((word) => text.includes(word));
    });
}

export interface WordSpan {
  start: number;
  end: number;
  text: string;
}

export function wordSpans(text: string): WordSpan[] {
  const spans: WordSpan[] = [];
  const points = Array.from(text);
  let start = -1;
  for (let index = 0; index <= points.length; index += 1) {
    const char = points[index];
    if (char !== undefined && /\S/u.test(char)) {
      if (start < 0) start = index;
    } else if (start >= 0) {
      spans.push({ start, end: index, text: points.slice(start, index).join('') });
      start = -1;
    }
  }
  return spans;
}

export function spanSelected(spans: readonly Span[], span: WordSpan): boolean {
  return spans.some((entry) => entry.start === span.start && entry.end === span.end);
}

export function toggleSpan(spans: readonly Span[], span: WordSpan): Span[] {
  const exists = spanSelected(spans, span);
  return exists
    ? spans.filter((entry) => entry.start !== span.start || entry.end !== span.end)
    : [...spans, { start: span.start, end: span.end }].sort((a, b) => a.start - b.start);
}
