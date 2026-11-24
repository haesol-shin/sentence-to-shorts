import { createAppendedScene, lineEntityId, sceneEntityId } from './fixture';
import type {
  Register,
  RewriteProposal,
  ScriptDocument,
  TargetDuration,
  ToneProposal,
  ToneSceneReview,
} from './types';

/** `Line.display_text` and `Line.speech_text` limits from the video contract. */
export const MAX_DISPLAY_CHARS = 300;
export const MAX_SPEECH_CHARS = 500;
/** The script screen and the edit panel both stop a scene at four lines. */
export const MAX_SCENE_LINES = 4;

const SECONDS_PER_CHARACTER = 5;

export const REGISTERS: readonly Register[] = ['friendly', 'neutral', 'casual'];

export const DURATIONS: readonly TargetDuration[] = [30, 60, 120];

/**
 * The scene-count choices come from the concept screen's own rule, read by the
 * app route. The feature keeps no second copy of the 30/60/120 mapping.
 */
let sceneCounts: readonly number[] = [];

export function configureScriptSceneCounts(counts: readonly number[]): void {
  sceneCounts = [...counts];
}

export function getScriptSceneCounts(): readonly number[] {
  return sceneCounts;
}

/** A contract character count: code points, not UTF-16 code units. */
export function textLength(text: string): number {
  return Array.from(text).length;
}

/** A mock estimate: five characters a second, rounded up to whole seconds. */
export function estimateLineSeconds(text: string): number {
  const characters = textLength(text.replace(/\s/gu, ''));
  return characters === 0 ? 0 : Math.max(1, Math.ceil(characters / SECONDS_PER_CHARACTER));
}

export function sceneSeconds(document: ScriptDocument, sceneId: string): number {
  const scene = document.scenes[sceneId];
  if (scene === undefined) {
    return 0;
  }
  return scene.lines.reduce((sum, line) => sum + estimateLineSeconds(line.display_text), 0);
}

export function totalSeconds(document: ScriptDocument): number {
  return document.scene_order.reduce((sum, id) => sum + sceneSeconds(document, id), 0);
}

/** The scene's place in the order, as the 「장면 N」 label counts it. */
export function sceneNumber(document: ScriptDocument, sceneId: string): number | null {
  const index = document.scene_order.indexOf(sceneId);
  return index < 0 ? null : index + 1;
}

export function isConfirmed(document: Pick<ScriptDocument, 'stage'>): boolean {
  return document.stage === 'script_confirmed' || document.stage === 'scenes_confirmed';
}

/** A scene with no line, or any line without text, cannot be confirmed. */
export function hasEmptyLine(document: ScriptDocument): boolean {
  return document.scene_order.some((id) => {
    const scene = document.scenes[id];
    if (scene === undefined) {
      return true;
    }
    return (
      scene.lines.length === 0 ||
      scene.lines.some(
        (line) => line.display_text.trim() === '' || line.speech_text.trim() === '',
      )
    );
  });
}

/** The scene order is a permutation of the scene set (CONTRACTS 1.3). */
export function hasDuplicateOrder(document: ScriptDocument): boolean {
  const ids = document.scene_order;
  return (
    new Set(ids).size !== ids.length ||
    ids.some((id) => document.scenes[id] === undefined) ||
    Object.keys(document.scenes).some((id) => !ids.includes(id))
  );
}

export interface LineIssue {
  sceneId: string;
  lineId: string;
}

export function firstTooLongLine(document: ScriptDocument): LineIssue | null {
  for (const sceneId of document.scene_order) {
    const scene = document.scenes[sceneId];
    if (scene === undefined) {
      continue;
    }
    for (const line of scene.lines) {
      if (
        textLength(line.display_text) > MAX_DISPLAY_CHARS ||
        textLength(line.speech_text) > MAX_SPEECH_CHARS
      ) {
        return { sceneId, lineId: line.id };
      }
    }
  }
  return null;
}

export function cloneDocument(document: ScriptDocument): ScriptDocument {
  return JSON.parse(JSON.stringify(document)) as ScriptDocument;
}

type Forms = Readonly<Record<Register, string>>;

/**
 * The endings the mock can re-say in all three speech levels. Irregular verbs
 * need their own row; the regular 하다 forms are covered by 해요/합니다/해.
 */
const TONE_FORMS: readonly (readonly [string, Forms])[] = (
  [
    ['주십시오', { friendly: '주세요', neutral: '주십시오', casual: '줘' }],
    ['주세요', { friendly: '주세요', neutral: '주십시오', casual: '줘' }],
    ['달라집니다', { friendly: '달라져요', neutral: '달라집니다', casual: '달라져' }],
    ['달라져요', { friendly: '달라져요', neutral: '달라집니다', casual: '달라져' }],
    ['달라져', { friendly: '달라져요', neutral: '달라집니다', casual: '달라져' }],
    ['맞춥니다', { friendly: '맞춰요', neutral: '맞춥니다', casual: '맞춰' }],
    ['맞춰요', { friendly: '맞춰요', neutral: '맞춥니다', casual: '맞춰' }],
    ['맞춰', { friendly: '맞춰요', neutral: '맞춥니다', casual: '맞춰' }],
    ['지킵니다', { friendly: '지켜요', neutral: '지킵니다', casual: '지켜' }],
    ['지켜요', { friendly: '지켜요', neutral: '지킵니다', casual: '지켜' }],
    ['지켜', { friendly: '지켜요', neutral: '지킵니다', casual: '지켜' }],
    ['봅니다', { friendly: '봐요', neutral: '봅니다', casual: '봐' }],
    ['봐요', { friendly: '봐요', neutral: '봅니다', casual: '봐' }],
    ['봐', { friendly: '봐요', neutral: '봅니다', casual: '봐' }],
    ['합니다', { friendly: '해요', neutral: '합니다', casual: '해' }],
    ['됩니다', { friendly: '돼요', neutral: '됩니다', casual: '돼' }],
    ['돼요', { friendly: '돼요', neutral: '됩니다', casual: '돼' }],
    ['돼', { friendly: '돼요', neutral: '됩니다', casual: '돼' }],
    ['어렵습니다', { friendly: '어려워요', neutral: '어렵습니다', casual: '어려워' }],
    ['어려워요', { friendly: '어려워요', neutral: '어렵습니다', casual: '어려워' }],
    ['어려워', { friendly: '어려워요', neutral: '어렵습니다', casual: '어려워' }],
    ['받습니다', { friendly: '받아요', neutral: '받습니다', casual: '받아' }],
    ['받아요', { friendly: '받아요', neutral: '받습니다', casual: '받아' }],
    ['받아', { friendly: '받아요', neutral: '받습니다', casual: '받아' }],
    ['길어집니다', { friendly: '길어져요', neutral: '길어집니다', casual: '길어져' }],
    ['길어져요', { friendly: '길어져요', neutral: '길어집니다', casual: '길어져' }],
    ['길어져', { friendly: '길어져요', neutral: '길어집니다', casual: '길어져' }],
    ['만납니다', { friendly: '만나요', neutral: '만납니다', casual: '만나' }],
    ['만나요', { friendly: '만나요', neutral: '만납니다', casual: '만나' }],
    ['만나', { friendly: '만나요', neutral: '만납니다', casual: '만나' }],
    ['해요', { friendly: '해요', neutral: '합니다', casual: '해' }],
    ['해', { friendly: '해요', neutral: '합니다', casual: '해' }],
    ['줘', { friendly: '주세요', neutral: '주십시오', casual: '줘' }],
  ] as const
).slice().sort((left, right) => right[0].length - left[0].length);

const ENDING = /^(.*?)([가-힣]+)([.!?]?)(["'’”)]?)$/u;

function shiftOneLine(line: string, to: Register): string {
  const match = ENDING.exec(line);
  if (match === null) {
    return line;
  }
  const [, head, word, punctuation, quote] = match;
  for (const [form, forms] of TONE_FORMS) {
    if (word.endsWith(form) && word.length >= form.length) {
      const stem = word.slice(0, word.length - form.length);
      return `${head}${stem}${forms[to]}${punctuation}${quote}`;
    }
  }
  return line;
}

/**
 * Re-say a line in another speech level. A line whose ending the mock does not
 * know stays as written, so a user sentence is never conjugated by guesswork.
 */
export function shiftTone(text: string, to: Register): string {
  return text
    .split('\n')
    .map((line) => shiftOneLine(line, to))
    .join('\n');
}

export function buildToneProposal(document: ScriptDocument, to: Register): ToneProposal {
  const scenes: ToneSceneReview[] = [];
  for (const sceneId of document.scene_order) {
    const scene = document.scenes[sceneId];
    if (scene === undefined) {
      continue;
    }
    const lines = scene.lines.flatMap((line) => {
      const after = shiftTone(line.display_text, to);
      return after === line.display_text
        ? []
        : [{ lineId: line.id, before: line.display_text, after }];
    });
    if (lines.length > 0) {
      scenes.push({ sceneId, lines });
    }
  }
  return { from: document.register, to, scenes };
}

export function withLineText(
  document: ScriptDocument,
  sceneId: string,
  lineId: string,
  text: string,
): ScriptDocument {
  const next = cloneDocument(document);
  const scene = next.scenes[sceneId];
  if (scene === undefined) {
    return document;
  }
  const line = scene.lines.find((entry) => entry.id === lineId);
  if (line === undefined) {
    return document;
  }
  line.display_text = text;
  line.speech_text = text;
  return next;
}

/**
 * Append one empty line to a scene. The caller edits its text in place, the
 * same way the edit panel's add-line draft settles into a line.
 */
export function withAddedLine(
  document: ScriptDocument,
  sceneId: string,
  lineFloor = 0,
): ScriptDocument {
  const next = cloneDocument(document);
  const scene = next.scenes[sceneId];
  if (scene === undefined) {
    return document;
  }
  const lineIds = Object.values(next.scenes).flatMap((entry) =>
    entry.lines.map((line) => line.id),
  );
  const nextLine = Math.max(maxEntityNumber(lineIds, 'l'), lineFloor) + 1;
  scene.lines = [
    ...scene.lines,
    { id: lineEntityId(nextLine), display_text: '', speech_text: '' },
  ];
  return next;
}

export function withSceneOrder(document: ScriptDocument, order: readonly string[]): ScriptDocument {
  if (new Set(order).size !== order.length || order.length !== document.scene_order.length) {
    return document;
  }
  if (order.some((id) => document.scenes[id] === undefined)) {
    return document;
  }
  return { ...cloneDocument(document), scene_order: [...order] };
}

export function maxEntityNumber(ids: Iterable<string>, prefix: 's' | 'l'): number {
  const pattern = prefix === 's' ? /^s_(\d{26})$/u : /^l_(\d{26})$/u;
  let max = 0;
  for (const id of ids) {
    const match = pattern.exec(id);
    if (match !== null) {
      const value = Number(match[1]);
      if (Number.isSafeInteger(value) && value > max) {
        max = value;
      }
    }
  }
  return max;
}

/**
 * Keep the head of the order and add or drop scenes at the tail. New scene and
 * line ids continue past every id the document has used, so a moved scene can
 * never collide with an appended one.
 */
export function withSceneCount(
  document: ScriptDocument,
  count: number,
  sceneFloor = 0,
  lineFloor = 0,
): ScriptDocument {
  const target = sceneCounts.includes(count) ? count : document.scene_order.length;
  const next = cloneDocument(document);
  const order = next.scene_order.slice(0, target);
  let nextScene = Math.max(maxEntityNumber(Object.keys(next.scenes), 's'), sceneFloor) + 1;
  let nextLine =
    Math.max(
      maxEntityNumber(
        Object.values(next.scenes).flatMap((scene) => scene.lines.map((line) => line.id)),
        'l',
      ),
      lineFloor,
    ) + 1;
  for (let index = order.length; index < target; index += 1) {
    const scene = createAppendedScene(sceneEntityId(nextScene), lineEntityId(nextLine));
    nextScene += 1;
    nextLine += 1;
    next.scenes[scene.id] = scene;
    order.push(scene.id);
  }
  const kept = new Set(order);
  for (const id of Object.keys(next.scenes)) {
    if (!kept.has(id)) {
      delete next.scenes[id];
    }
  }
  next.scene_order = order;
  return next;
}

export function withDuration(document: ScriptDocument, duration: TargetDuration): ScriptDocument {
  return { ...document, target_duration_s: duration };
}

const REWRITE_PREFIX = '다시 말하면, ';

/**
 * The mock rewrite says the first line again with a different lead-in. The
 * real script job owns wording; this keeps the review honest and repeatable.
 */
export function rewriteLines(lines: readonly string[]): string[] {
  return lines.map((text, index) => {
    const plain = text.startsWith(REWRITE_PREFIX) ? text.slice(REWRITE_PREFIX.length) : text;
    return index === 0 ? `${REWRITE_PREFIX}${plain}` : plain;
  });
}

export function buildRewriteProposal(
  document: ScriptDocument,
  sceneId: string,
): RewriteProposal | null {
  const scene = document.scenes[sceneId];
  if (scene === undefined) {
    return null;
  }
  const before = scene.lines.map((line) => line.display_text);
  return { sceneId, before, after: rewriteLines(before) };
}
