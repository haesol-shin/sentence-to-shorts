import type {
  CardTune,
  Character,
  ConceptCatalog,
  LockKey,
  Origin,
  PinnedRef,
  Plan,
  Settings,
  SetOp,
  Slot,
  StyleManifest,
} from './types';

export const ORIGIN_RANK: Record<Origin, number> = {
  user: 6,
  reference: 5,
  preset: 4,
  card: 3,
  llm: 2,
  default: 1,
  derived: 0,
};

export const SLOTS: readonly Slot[] = ['body', 'face', 'hair', 'hat', 'outfit', 'prop'];

function isSlot(value: string): value is Slot {
  return (SLOTS as readonly string[]).includes(value);
}

export const CONCEPT_LOCK_KEYS: readonly LockKey[] = [
  'story_structure',
  'layout',
  'character_role',
  'register',
  'humor',
  'art_style',
  'theme',
  'character',
  'voice',
  'bgm',
  'caption_mode',
  'caption_font',
  'background',
  'transition',
];

export const PIXEL_REF: PinnedRef = {
  id: 'pixel',
  revision: '6996966228988901a42e3e3f5d19ddc19ffd005bd3c9f1047ca979fcd3a98e20',
};

export const DEFAULT_FONT_REF: PinnedRef = {
  id: 'galmuri11',
  revision: 'd92c304c2bc07f41810bf938c71bd8a9cab36e27fcb980bbb98a6ffb27098c75',
};

export const LAYOUT_REFS: Record<'fixed_stage' | 'full_stage' | 'dialog_stage', PinnedRef> = {
  fixed_stage: {
    id: 'fixed_stage',
    revision: 'cefcb99666d9e8b563eb21eb6ef889b4a338616e98cc2350093ac6591072e05d',
  },
  full_stage: {
    id: 'full_stage',
    revision: 'fed4c5d263c996ad961ef14effd2b72f9a181014d0929a83fc46798efe825c1a',
  },
  dialog_stage: {
    id: 'dialog_stage',
    revision: '19b9251da9fa3b9531d6a9b78a23c37fde5b39af24f97b8c72620b67ec1d8682',
  },
};

export const DEFAULT_CHARACTER: Character = {
  preset_id: null,
  slots: {
    body: 'body_hero',
    face: 'face_neutral',
    hair: null,
    hat: null,
    outfit: null,
    prop: null,
  },
};

export interface CardPreset {
  storyStructure: 'numbered_three' | 'single_analogy' | 'hypothetical';
  layout: 'fixed_stage' | 'full_stage' | 'dialog_stage';
  role: 'none' | 'presenter' | 'subject';
  register: 'friendly' | 'neutral' | 'casual';
  humor: 'none' | 'light';
  progress: 'numbered' | 'phases' | 'none';
  caption: 'sentence' | 'phrase' | 'typewriter';
}

export const CARD_PRESETS: Record<string, CardPreset> = {
  just_three: {
    storyStructure: 'numbered_three',
    layout: 'fixed_stage',
    role: 'presenter',
    register: 'friendly',
    humor: 'none',
    progress: 'numbered',
    caption: 'sentence',
  },
  its_like: {
    storyStructure: 'single_analogy',
    layout: 'full_stage',
    role: 'subject',
    register: 'friendly',
    humor: 'light',
    progress: 'phases',
    caption: 'phrase',
  },
  what_if: {
    storyStructure: 'hypothetical',
    layout: 'full_stage',
    role: 'subject',
    register: 'friendly',
    humor: 'light',
    progress: 'phases',
    caption: 'phrase',
  },
};

export function cardTunePreset(
  cardId: string | null,
  catalog: ConceptCatalog | null,
): CardTune | null {
  const preset = cardId === null ? undefined : CARD_PRESETS[cardId];
  const layout = preset === undefined ? null : resolveLayoutRef(catalog, preset.layout);
  if (preset === undefined || layout === null) return null;
  return {
    layout,
    role: preset.role,
    register: preset.register,
    humor: preset.humor,
  };
}

export function cardTuneOf(settings: Settings): CardTune {
  return {
    layout: settings.format.layout,
    role: settings.format.character_role,
    register: settings.format.register,
    humor: settings.format.humor,
  };
}

/** The one card a settings value follows, even before the first card click. */
export function cardIdForSettings(settings: Settings): string | null {
  if (settings.format.card_id !== null) return settings.format.card_id;
  return Object.entries(CARD_PRESETS)
    .find(([, preset]) => preset.storyStructure === settings.format.story_structure)?.[0] ?? null;
}

export const SHORT_OPTIONS = {
  story_structure: ['numbered_three', 'single_analogy', 'hypothetical'],
  character_role: ['none', 'presenter', 'subject'],
  register: ['friendly', 'neutral', 'casual'],
  humor: ['none', 'light'],
  caption_mode: ['sentence', 'phrase', 'typewriter'],
  progress_mode: ['numbered', 'phases', 'none'],
  transition: ['cut', 'fade'],
  character_motion: ['none', 'pop', 'bob'],
} as const;

const DURATIONS = [30, 60, 120] as const;

export function recommendedSceneCount(duration: number): number {
  if (duration >= 120) {
    return 11;
  }
  return duration >= 60 ? 8 : 5;
}

export function normalizeDuration(duration: number | undefined): 30 | 60 | 120 {
  return DURATIONS.includes(duration as (typeof DURATIONS)[number])
    ? (duration as 30 | 60 | 120)
    : 30;
}

export interface ValidationIssue {
  code:
    | 'unknown_catalog_id'
    | 'typewriter_layout'
    | 'role_none_character'
    | 'character_missing'
    | 'incompatible_part'
    | 'invalid_combination';
  path: string;
  key: string;
}

export interface ConceptValidation {
  blocked: ValidationIssue[];
  warnings: ValidationIssue[];
  ok: boolean;
}

export interface SettingsChange {
  kind: 'changed';
  settings: Settings;
  editedPaths: string[];
}

export interface ReplacementChange {
  kind: 'replacement';
  ops: SetOp[];
  editedPaths: string[];
}

export interface InvalidChange {
  kind: 'invalid';
  issue: ValidationIssue;
}

export type ChangeResult = SettingsChange | ReplacementChange | InvalidChange;

function issue(
  code: ValidationIssue['code'],
  path: string,
  key: string,
): ValidationIssue {
  return { code, path, key };
}

export const ISSUE_KEYS = {
  characterNone: 'concept.reason.characterNoneWithParts',
  characterMissing: 'concept.reason.characterMissing',
  typewriter: 'concept.reason.typewriterNeedsDialog',
  unknownAsset: 'concept.reason.unknownAsset',
  unknownStyle: 'concept.reason.unknownStyle',
  unknownTheme: 'concept.reason.unknownTheme',
  unknownLayout: 'concept.reason.unknownLayout',
  unknownFont: 'concept.reason.unknownFont',
  weak: 'concept.reason.weakCombination',
  invalid: 'concept.reason.invalidValue',
} as const;

export function cloneSettings(settings: Settings): Settings {
  return JSON.parse(JSON.stringify(settings)) as Settings;
}

export function normalizePointer(path: string): string | null {
  if (!path.startsWith('/') || path === '/' || path.endsWith('/')) {
    return null;
  }
  const parts = path
    .slice(1)
    .split('/')
    .map((part) => part.replaceAll('~1', '/').replaceAll('~0', '~'));
  if (parts.some((part) => part === '' || part === '__proto__' || part === 'constructor' || part === 'prototype')) {
    return null;
  }
  return `/${parts.join('/')}`;
}

export function getSettingsValue(settings: Settings, path: string): unknown {
  const pointer = normalizePointer(path);
  if (pointer === null) {
    return undefined;
  }
  let current: unknown = settings;
  for (const part of pointer.slice(1).split('/')) {
    if (current === null || typeof current !== 'object') {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

function setAtPath(target: Record<string, unknown>, parts: string[], value: unknown): void {
  let current = target;
  for (const [index, part] of parts.entries()) {
    const last = index === parts.length - 1;
    if (last) {
      current[part] = value;
      return;
    }
    const child = current[part];
    if (child === null || typeof child !== 'object' || Array.isArray(child)) {
      current[part] = {};
    }
    current = current[part] as Record<string, unknown>;
  }
}

export function withSettingsValue(settings: Settings, path: string, value: unknown): Settings {
  const pointer = normalizePointer(path);
  if (pointer === null) {
    return settings;
  }
  const next = cloneSettings(settings);
  setAtPath(next as unknown as Record<string, unknown>, pointer.slice(1).split('/'), value);
  return next;
}

export function applySettingsOps(settings: Settings, ops: readonly SetOp[]): Settings {
  let next = settings;
  for (const op of ops) {
    if (op.op === 'set') {
      next = withSettingsValue(next, op.path, op.value);
      next.origins[op.path] = op.origin;
      const aggregate = originPath(op.path);
      if (aggregate !== op.path) {
        next.origins[aggregate] = op.origin;
      }
    }
  }
  return next;
}

export function originPath(path: string): string {
  return path.startsWith('/visual/character') ? '/visual/character' : path;
}

export function withOrigin(settings: Settings, path: string, origin: Origin): Settings {
  const next = cloneSettings(settings);
  next.origins[path] = origin;
  const aggregate = originPath(path);
  if (aggregate !== path) {
    next.origins[aggregate] = origin;
  }
  return next;
}

export function originOf(settings: Settings, path: string): Origin {
  return settings.origins[originPath(path)] ?? settings.origins[path] ?? 'default';
}

export function lockKeyForPath(path: string): LockKey | null {
  if (path === '/format/story_structure' || path === '/format/card_id') {
    return 'story_structure';
  }
  if (path === '/format/layout') {
    return 'layout';
  }
  if (path === '/format/character_role' || path.startsWith('/visual/character')) {
    return 'character';
  }
  if (path === '/format/register') {
    return 'register';
  }
  if (path === '/format/humor') {
    return 'humor';
  }
  if (path === '/visual/art_style') {
    return 'art_style';
  }
  if (path === '/visual/theme_id') {
    return 'theme';
  }
  if (path === '/caption/mode') {
    return 'caption_mode';
  }
  if (path === '/caption/font_id') {
    return 'caption_font';
  }
  if (path === '/motion/transition') {
    return 'transition';
  }
  return null;
}

export function isConceptLockedPath(path: string): boolean {
  return (
    path === '/format/card_id' ||
    path === '/format/story_structure' ||
    path === '/format/character_role' ||
    path.startsWith('/visual/character') ||
    path === '/visual/art_style'
  );
}

export function planTouchesLockedFields(ops: readonly SetOp[]): boolean {
  return ops.some((op) => isConceptLockedPath(op.path));
}

function activeManifest(settings: Settings, catalog: ConceptCatalog | null): StyleManifest | null {
  if (catalog === null) {
    return null;
  }
  return (
    catalog.styles.find((style) => style.ref.id === settings.visual.art_style.id)?.manifest ?? null
  );
}

export function activeStyleManifest(
  settings: Settings,
  catalog: ConceptCatalog | null,
): StyleManifest | null {
  return activeManifest(settings, catalog);
}

function hasAsset(manifest: StyleManifest | null, slot: Slot, assetId: string | null): boolean {
  if (assetId === null) {
    return true;
  }
  if (manifest === null) {
    return true;
  }
  return manifest.assets.some(
    (asset) => asset.id === assetId && asset.kind === 'part' && asset.slot === slot,
  );
}

function firstAsset(manifest: StyleManifest | null, slot: Slot): string | null {
  if (manifest === null) {
    return DEFAULT_CHARACTER.slots[slot];
  }
  return manifest.assets.find((asset) => asset.kind === 'part' && asset.slot === slot)?.id ?? null;
}

export function defaultCharacter(
  settings: Settings,
  catalog: ConceptCatalog | null,
): Character {
  const manifest = activeManifest(settings, catalog);
  return {
    preset_id: null,
    slots: {
      body: firstAsset(manifest, 'body') ?? DEFAULT_CHARACTER.slots.body,
      face: firstAsset(manifest, 'face') ?? DEFAULT_CHARACTER.slots.face,
      hair: null,
      hat: null,
      outfit: null,
      prop: null,
    },
  };
}

function resolveLayoutRef(catalog: ConceptCatalog | null, id: string): PinnedRef | null {
  return catalog?.layouts.find((entry) => entry.ref.id === id)?.ref ?? LAYOUT_REFS[id as keyof typeof LAYOUT_REFS] ?? null;
}

function dialogBoxFor(settings: Settings, catalog: ConceptCatalog | null): boolean {
  const id = settings.format.layout.id;
  const entry = catalog?.layouts.find((layout) => layout.ref.id === id);
  return entry?.dialogBox ?? id === 'dialog_stage';
}

function resolveStyleRef(
  catalog: ConceptCatalog | null,
  value: unknown,
): PinnedRef | null {
  if (value !== null && typeof value === 'object' && 'id' in value && 'revision' in value) {
    const ref = value as PinnedRef;
    const known = catalog?.styles.find((style) => style.ref.id === ref.id)?.ref;
    return known ?? ref;
  }
  if (typeof value !== 'string') {
    return null;
  }
  return catalog?.styles.find((style) => style.ref.id === value)?.ref ?? null;
}

function resolveTheme(manifest: StyleManifest | null, value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  if (manifest === null) {
    return value;
  }
  return manifest.themes.some((theme) => theme.id === value) ? value : null;
}

function resolveFont(catalog: ConceptCatalog | null, value: unknown): PinnedRef | null {
  if (value !== null && typeof value === 'object' && 'id' in value && 'revision' in value) {
    const ref = value as PinnedRef;
    const known = catalog?.fonts?.find((font) => font.id === ref.id);
    return known ?? ref;
  }
  if (typeof value !== 'string') {
    return null;
  }
  const known = catalog?.fonts?.find((font) => font.id === value);
  return known ?? (value === DEFAULT_FONT_REF.id ? DEFAULT_FONT_REF : null);
}

function filteredCharacter(
  character: Character | null,
  manifest: StyleManifest | null,
): { character: Character | null; ops: SetOp[] } {
  if (character === null) {
    return { character: null, ops: [] };
  }
  const slots = { ...character.slots };
  const ops: SetOp[] = [];
  for (const slot of SLOTS) {
    const asset = slots[slot];
    if (asset !== null && hasAsset(manifest, slot, asset) === false) {
      const replacement = firstAsset(manifest, slot);
      if (slot === 'body' || slot === 'face') {
        slots[slot] = replacement ?? DEFAULT_CHARACTER.slots[slot];
      } else {
        slots[slot] = replacement;
      }
      ops.push({
        op: 'set',
        path: `/visual/character/slots/${slot}`,
        value: slots[slot],
        origin: 'default',
      });
    }
  }
  return { character: { preset_id: character.preset_id, slots }, ops };
}

function styleSwitch(
  settings: Settings,
  target: PinnedRef,
  origin: Origin,
  catalog: ConceptCatalog | null,
): ChangeResult {
  const targetStyle = catalog?.styles.find((style) => style.ref.id === target.id);
  if (targetStyle === undefined && catalog !== null) {
    return { kind: 'invalid', issue: issue('unknown_catalog_id', '/visual/art_style', ISSUE_KEYS.unknownStyle) };
  }
  const manifest = targetStyle?.manifest ?? null;
  const filtered = filteredCharacter(settings.visual.character, manifest);
  const theme =
    manifest === null || manifest.themes.some((entry) => entry.id === settings.visual.theme_id)
      ? settings.visual.theme_id
      : manifest.themes[0]?.id;
  if (theme === undefined) {
    return { kind: 'invalid', issue: issue('unknown_catalog_id', '/visual/theme_id', ISSUE_KEYS.unknownTheme) };
  }

  const editedPaths = ['/visual/art_style', '/visual/character'];
  const ops: SetOp[] = [
    { op: 'set', path: '/visual/art_style', value: target, origin },
  ];
  if (theme !== settings.visual.theme_id) {
    editedPaths.push('/visual/theme_id');
    ops.push({ op: 'set', path: '/visual/theme_id', value: theme, origin: 'default' });
  }
  ops.push(...filtered.ops.map((op) => ({ ...op, origin })));

  if (ops.length === 1 && settings.visual.art_style.id === target.id) {
    return { kind: 'changed', settings, editedPaths: [] };
  }
  if (filtered.ops.length > 0) {
    return { kind: 'replacement', ops, editedPaths };
  }

  let next = withSettingsValue(settings, '/visual/art_style', target);
  next.origins['/visual/art_style'] = origin;
  if (theme !== settings.visual.theme_id) {
    next = withSettingsValue(next, '/visual/theme_id', theme);
    next.origins['/visual/theme_id'] = 'default';
  }
  return { kind: 'changed', settings: next, editedPaths };
}

function characterForRole(
  settings: Settings,
  role: 'none' | 'presenter' | 'subject',
  catalog: ConceptCatalog | null,
): Character | null {
  if (role === 'none') {
    return null;
  }
  const current = settings.visual.character;
  if (current !== null && current.slots.body !== null && current.slots.face !== null) {
    return current;
  }
  return defaultCharacter(settings, catalog);
}

function applySimple(
  settings: Settings,
  path: string,
  value: unknown,
): ChangeResult {
  const current = getSettingsValue(settings, path);
  if (JSON.stringify(current) === JSON.stringify(value)) {
    return { kind: 'changed', settings, editedPaths: [] };
  }
  let next = withSettingsValue(settings, path, value);
  next = withOrigin(next, path, 'user');
  return { kind: 'changed', settings: next, editedPaths: [path] };
}

const ROLE_VALUES = ['none', 'presenter', 'subject'] as const;
const REGISTER_VALUES = SHORT_OPTIONS.register;
const HUMOR_VALUES = SHORT_OPTIONS.humor;
const CAPTION_VALUES = SHORT_OPTIONS.caption_mode;
const PROGRESS_VALUES = SHORT_OPTIONS.progress_mode;
const TRANSITION_VALUES = SHORT_OPTIONS.transition;
const MOTION_VALUES = SHORT_OPTIONS.character_motion;
const STORY_VALUES = SHORT_OPTIONS.story_structure;

function allowed<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === 'string' && (values as readonly string[]).includes(value);
}

/**
 * Applies one settings-relative pointer as a user edit. Blocked combinations
 * are returned instead of written, so callers never store an invalid state.
 */
export function changeConceptValue(
  settings: Settings,
  path: string,
  value: unknown,
  catalog: ConceptCatalog | null,
): ChangeResult {
  const pointer = normalizePointer(path);
  if (pointer === null) {
    return { kind: 'invalid', issue: issue('invalid_combination', path, ISSUE_KEYS.invalid) };
  }

  if (pointer === '/format/character_role') {
    if (!allowed(ROLE_VALUES, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    let next = withSettingsValue(settings, '/format/character_role', value);
    const character = characterForRole(settings, value, catalog);
    next = withSettingsValue(next, '/visual/character', character);
    next = withOrigin(next, '/format/character_role', 'user');
    next = withOrigin(next, '/visual/character', 'user');
    const validation = validateConcept(next, catalog);
    if (!validation.ok) {
      return { kind: 'invalid', issue: validation.blocked[0] };
    }
    return {
      kind: 'changed',
      settings: next,
      editedPaths: ['/format/character_role', '/visual/character'],
    };
  }

  if (pointer === '/visual/character') {
    if (value !== null && (typeof value !== 'object' || !('slots' in value))) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    const next = withOrigin(withSettingsValue(settings, pointer, value), pointer, 'user');
    const validation = validateConcept(next, catalog);
    if (!validation.ok) {
      return { kind: 'invalid', issue: validation.blocked[0] };
    }
    return { kind: 'changed', settings: next, editedPaths: [pointer] };
  }

  if (pointer.startsWith('/visual/character/slots/')) {
    const slot = pointer.slice('/visual/character/slots/'.length);
    if (!isSlot(slot) || !(value === null || typeof value === 'string')) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    if (settings.format.character_role === 'none') {
      return { kind: 'invalid', issue: issue('role_none_character', pointer, ISSUE_KEYS.characterNone) };
    }
    if ((slot === 'body' || slot === 'face') && value === null) {
      return { kind: 'invalid', issue: issue('character_missing', pointer, ISSUE_KEYS.characterMissing) };
    }
    const character = settings.visual.character ?? defaultCharacter(settings, catalog);
    const slots = { ...character.slots };
    if (slot === 'body' || slot === 'face') {
      slots[slot] = value as string;
    } else {
      slots[slot] = value;
    }
    const nextCharacter: Character = { preset_id: character.preset_id, slots };
    let next = withSettingsValue(settings, '/visual/character', nextCharacter);
    next = withOrigin(next, '/visual/character', 'user');
    const validation = validateConcept(next, catalog);
    if (!validation.ok) {
      return { kind: 'invalid', issue: validation.blocked[0] };
    }
    return { kind: 'changed', settings: next, editedPaths: ['/visual/character'] };
  }

  if (pointer === '/visual/art_style') {
    const target = resolveStyleRef(catalog, value);
    if (target === null) {
      return { kind: 'invalid', issue: issue('unknown_catalog_id', pointer, ISSUE_KEYS.unknownStyle) };
    }
    return styleSwitch(settings, target, 'user', catalog);
  }

  if (pointer === '/visual/theme_id') {
    const manifest = activeManifest(settings, catalog);
    const theme = resolveTheme(manifest, value);
    if (theme === null) {
      return { kind: 'invalid', issue: issue('unknown_catalog_id', pointer, ISSUE_KEYS.unknownTheme) };
    }
    return applySimple(settings, pointer, theme);
  }

  if (pointer === '/format/layout') {
    const id = value !== null && typeof value === 'object' && 'id' in value && 'revision' in value
      ? String(value.id)
      : typeof value === 'string'
        ? value
        : null;
    const pinned = value !== null && typeof value === 'object' && 'id' in value && 'revision' in value
      ? (value as PinnedRef)
      : null;
    const ref = pinned ?? (id === null ? null : resolveLayoutRef(catalog, id));
    if (ref === null) {
      return { kind: 'invalid', issue: issue('unknown_catalog_id', pointer, ISSUE_KEYS.unknownLayout) };
    }
    const candidate = withSettingsValue(settings, pointer, ref);
    const dialogBox = catalog?.layouts.find((layout) => layout.ref.id === ref.id)?.dialogBox
      ?? ref.id === 'dialog_stage';
    if (candidate.caption.mode === 'typewriter' && dialogBox === false) {
      return { kind: 'invalid', issue: issue('typewriter_layout', '/caption/mode', ISSUE_KEYS.typewriter) };
    }
    return applySimple(settings, pointer, ref);
  }

  if (pointer === '/format/card_id') {
    if (!(value === null || (typeof value === 'string' && value in CARD_PRESETS))) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/format/story_structure') {
    if (!allowed(STORY_VALUES, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/format/register') {
    if (!allowed(REGISTER_VALUES, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/format/humor') {
    if (!allowed(HUMOR_VALUES, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/format/progress_mode') {
    if (!allowed(PROGRESS_VALUES, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/format/scene_count') {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > 30) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/target_duration_s') {
    if (!DURATIONS.includes(value as (typeof DURATIONS)[number])) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    let next = withSettingsValue(settings, pointer, value);
    next = withOrigin(next, pointer, 'user');
    if (originOf(settings, '/format/scene_count') === 'default') {
      next = withSettingsValue(next, '/format/scene_count', recommendedSceneCount(value as number));
      next = withOrigin(next, '/format/scene_count', 'llm');
    }
    return { kind: 'changed', settings: next, editedPaths: [pointer] };
  }

  if (pointer === '/caption/mode') {
    if (!allowed(CAPTION_VALUES, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    if (value === 'typewriter' && dialogBoxFor(settings, catalog) === false) {
      return { kind: 'invalid', issue: issue('typewriter_layout', pointer, ISSUE_KEYS.typewriter) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/caption/font_id') {
    const font = resolveFont(catalog, value);
    if (font === null) {
      return { kind: 'invalid', issue: issue('unknown_catalog_id', pointer, ISSUE_KEYS.unknownFont) };
    }
    return applySimple(settings, pointer, font);
  }

  if (pointer === '/caption/position') {
    if (!allowed(['top', 'middle', 'bottom'] as const, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/caption/highlight') {
    if (typeof value !== 'boolean') {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/motion/transition') {
    if (!allowed(TRANSITION_VALUES, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/motion/character_motion') {
    if (!allowed(MOTION_VALUES, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/audio/bgm/enabled' || pointer === '/audio/sfx_enabled') {
    if (typeof value !== 'boolean') {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/audio/bgm/mood') {
    if (!allowed(['curious', 'playful', 'tense', 'energetic', 'calm', 'reflective'] as const, value)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/audio/bgm/gain_db_x10') {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < -600 || value > 0) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/audio/bgm/ducking') {
    if (typeof value !== 'boolean') {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/language') {
    if (value !== 'ko' && value !== 'en') {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  if (pointer === '/extra_instructions') {
    if (!Array.isArray(value) || value.some((entry) => typeof entry !== 'string')) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    return applySimple(settings, pointer, value);
  }

  return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
}

function withDefaultOrigin(
  settings: Settings,
  path: string,
  value: unknown,
  catalog: ConceptCatalog | null,
): ChangeResult {
  const current = getSettingsValue(settings, path);
  if (JSON.stringify(current) === JSON.stringify(value)) {
    return { kind: 'changed', settings, editedPaths: [] };
  }
  let next = withSettingsValue(settings, path, value);
  next = withOrigin(next, originPath(path), 'default');
  const validation = validateConcept(next, catalog);
  if (!validation.ok) {
    return { kind: 'invalid', issue: validation.blocked[0] };
  }
  return { kind: 'changed', settings: next, editedPaths: [path] };
}

export function resetConceptValue(
  settings: Settings,
  path: string,
  catalog: ConceptCatalog | null,
): ChangeResult {
  const pointer = normalizePointer(path);
  if (pointer === null) {
    return { kind: 'invalid', issue: issue('invalid_combination', path, ISSUE_KEYS.invalid) };
  }
  if (pointer === '/format/character_role') {
    let next = withSettingsValue(settings, '/format/character_role', 'presenter');
    next = withSettingsValue(next, '/visual/character', defaultCharacter(settings, catalog));
    next = withOrigin(next, '/format/character_role', 'default');
    next = withOrigin(next, '/visual/character', 'default');
    const validation = validateConcept(next, catalog);
    if (!validation.ok) {
      return { kind: 'invalid', issue: validation.blocked[0] };
    }
    return { kind: 'changed', settings: next, editedPaths: ['/format/character_role', '/visual/character'] };
  }
  if (pointer === '/visual/character') {
    const value = settings.format.character_role === 'none' ? null : defaultCharacter(settings, catalog);
    return withDefaultOrigin(settings, pointer, value, catalog);
  }
  if (pointer.startsWith('/visual/character/slots/')) {
    const slot = pointer.slice('/visual/character/slots/'.length);
    if (!isSlot(slot)) {
      return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
    }
    if (settings.format.character_role === 'none') {
      return { kind: 'invalid', issue: issue('role_none_character', pointer, ISSUE_KEYS.characterNone) };
    }
    const character = settings.visual.character ?? defaultCharacter(settings, catalog);
    const manifest = activeManifest(settings, catalog);
    const slots = { ...character.slots };
    if (slot === 'body' || slot === 'face') {
      slots[slot] = firstAsset(manifest, slot) ?? DEFAULT_CHARACTER.slots[slot];
    } else {
      slots[slot] = null;
    }
    const nextCharacter: Character = { preset_id: character.preset_id, slots };
    return withDefaultOrigin(settings, '/visual/character', nextCharacter, catalog);
  }
  if (pointer === '/visual/art_style') {
    return styleSwitch(settings, PIXEL_REF, 'default', catalog);
  }
  if (pointer === '/visual/theme_id') {
    const manifest = activeManifest(settings, catalog);
    const theme = manifest?.themes[0]?.id ?? 'day';
    return withDefaultOrigin(settings, pointer, theme, catalog);
  }
  if (pointer === '/format/layout') {
    return withDefaultOrigin(settings, pointer, LAYOUT_REFS.fixed_stage, catalog);
  }
  if (pointer === '/format/card_id') {
    return withDefaultOrigin(settings, pointer, null, catalog);
  }
  if (pointer === '/format/scene_count') {
    return withDefaultOrigin(settings, pointer, recommendedSceneCount(settings.target_duration_s), catalog);
  }
  if (pointer === '/target_duration_s') {
    let next = withSettingsValue(settings, pointer, 30);
    next = withOrigin(next, pointer, 'default');
    if (originOf(settings, '/format/scene_count') !== 'user') {
      next = withSettingsValue(next, '/format/scene_count', 5);
      next = withOrigin(next, '/format/scene_count', 'default');
    }
    return { kind: 'changed', settings: next, editedPaths: [pointer] };
  }
  if (pointer === '/format/story_structure') {
    return withDefaultOrigin(settings, pointer, 'numbered_three', catalog);
  }
  if (pointer === '/format/register') {
    return withDefaultOrigin(settings, pointer, 'friendly', catalog);
  }
  if (pointer === '/format/humor') {
    return withDefaultOrigin(settings, pointer, 'none', catalog);
  }
  if (pointer === '/format/progress_mode') {
    return withDefaultOrigin(settings, pointer, 'numbered', catalog);
  }
  if (pointer === '/caption/mode') {
    return withDefaultOrigin(settings, pointer, 'sentence', catalog);
  }
  if (pointer === '/caption/font_id') {
    return withDefaultOrigin(settings, pointer, catalog?.fonts?.[0] ?? DEFAULT_FONT_REF, catalog);
  }
  if (pointer === '/caption/position') {
    return withDefaultOrigin(settings, pointer, 'bottom', catalog);
  }
  if (pointer === '/caption/highlight') {
    return withDefaultOrigin(settings, pointer, true, catalog);
  }
  if (pointer === '/motion/transition') {
    return withDefaultOrigin(settings, pointer, 'cut', catalog);
  }
  if (pointer === '/motion/character_motion') {
    return withDefaultOrigin(settings, pointer, 'none', catalog);
  }
  if (pointer === '/audio/bgm/enabled') {
    return withDefaultOrigin(settings, pointer, true, catalog);
  }
  if (pointer === '/audio/bgm/mood') {
    return withDefaultOrigin(settings, pointer, 'curious', catalog);
  }
  if (pointer === '/audio/bgm/gain_db_x10') {
    return withDefaultOrigin(settings, pointer, -120, catalog);
  }
  if (pointer === '/audio/bgm/ducking') {
    return withDefaultOrigin(settings, pointer, true, catalog);
  }
  if (pointer === '/audio/sfx_enabled') {
    return withDefaultOrigin(settings, pointer, true, catalog);
  }
  if (pointer === '/extra_instructions') {
    return withDefaultOrigin(settings, pointer, [], catalog);
  }
  return { kind: 'invalid', issue: issue('invalid_combination', pointer, ISSUE_KEYS.invalid) };
}

/**
 * A card fills format values below the origin rank of the card. Values the
 * user or a reference already chose are left alone, as SPEC 3 requires.
 */
export function changeCard(
  settings: Settings,
  cardId: string,
  duration: number,
  catalog: ConceptCatalog | null,
): ChangeResult {
  const preset = CARD_PRESETS[cardId];
  if (preset === undefined) {
    return { kind: 'invalid', issue: issue('invalid_combination', '/format/card_id', ISSUE_KEYS.invalid) };
  }
  let next = cloneSettings(settings);
  const editedPaths: string[] = ['/format/card_id'];
  next = withSettingsValue(next, '/format/card_id', cardId);
  next.origins['/format/card_id'] = 'card';

  const fill = (path: string, value: unknown): void => {
    if (ORIGIN_RANK[originOf(next, path)] > ORIGIN_RANK.card) {
      return;
    }
    next = withSettingsValue(next, path, value);
    next.origins[originPath(path)] = 'card';
    editedPaths.push(path);
  };

  fill('/format/story_structure', preset.storyStructure);
  fill('/format/layout', resolveLayoutRef(catalog, preset.layout));
  fill('/format/register', preset.register);
  fill('/format/humor', preset.humor);
  fill('/format/progress_mode', preset.progress);
  fill('/caption/mode', preset.caption);
  fill('/format/scene_count', recommendedSceneCount(duration));

  if (originOf(next, '/format/character_role') !== 'user') {
    next = withSettingsValue(next, '/format/character_role', preset.role);
    next = withSettingsValue(next, '/visual/character', characterForRole(next, preset.role, catalog));
    next.origins['/format/character_role'] = 'card';
    next.origins['/visual/character'] = 'card';
    editedPaths.push('/format/character_role', '/visual/character');
  }

  const validation = validateConcept(next, catalog);
  if (!validation.ok) {
    return { kind: 'invalid', issue: validation.blocked[0] };
  }
  return { kind: 'changed', settings: next, editedPaths };
}

/**
 * Select a story card together with the four values shown beside it. Unlike
 * `changeCard`, the card's own values win even when the user edited them on
 * another card, because each card keeps its own fine-tune row.
 */
export function changeCardTune(
  settings: Settings,
  cardId: string,
  tune: CardTune,
  duration: number,
  catalog: ConceptCatalog | null,
): ChangeResult {
  const preset = CARD_PRESETS[cardId];
  const presetLayout = resolveLayoutRef(catalog, preset?.layout ?? '');
  if (preset === undefined || presetLayout === null) {
    return { kind: 'invalid', issue: issue('invalid_combination', '/format/card_id', ISSUE_KEYS.invalid) };
  }
  let next = cloneSettings(settings);
  const editedPaths: string[] = [];
  const set = (path: string, value: unknown, origin: Origin): void => {
    next = withSettingsValue(next, path, value);
    next.origins[originPath(path)] = origin;
    editedPaths.push(path);
  };

  set('/format/card_id', cardId, 'card');
  set('/format/story_structure', preset.storyStructure, 'card');

  const fill = (path: string, value: unknown): void => {
    if (ORIGIN_RANK[originOf(next, path)] > ORIGIN_RANK.card) {
      return;
    }
    next = withSettingsValue(next, path, value);
    next.origins[originPath(path)] = 'card';
    editedPaths.push(path);
  };
  fill('/format/progress_mode', preset.progress);
  fill('/caption/mode', preset.caption);
  fill('/format/scene_count', recommendedSceneCount(duration));

  const layoutSame = JSON.stringify(tune.layout) === JSON.stringify(presetLayout);
  set('/format/layout', tune.layout, layoutSame ? 'card' : 'user');
  set('/format/register', tune.register, tune.register === preset.register ? 'card' : 'user');
  set('/format/humor', tune.humor, tune.humor === preset.humor ? 'card' : 'user');

  const roleChanged = settings.format.character_role !== tune.role;
  set('/format/character_role', tune.role, tune.role === preset.role ? 'card' : 'user');
  if (roleChanged || (next.visual.character === null && tune.role !== 'none')) {
    next = withSettingsValue(next, '/visual/character', characterForRole(next, tune.role, catalog));
    next.origins['/visual/character'] = tune.role === preset.role ? 'card' : 'user';
    editedPaths.push('/visual/character');
  }

  const validation = validateConcept(next, catalog);
  if (!validation.ok) {
    return { kind: 'invalid', issue: validation.blocked[0] };
  }
  return { kind: 'changed', settings: next, editedPaths };
}

export function validateConcept(
  settings: Settings,
  catalog: ConceptCatalog | null,
): ConceptValidation {
  const blocked: ValidationIssue[] = [];
  const warnings: ValidationIssue[] = [];
  const push = (list: ValidationIssue[], value: ValidationIssue): void => {
    if (!list.some((entry) => entry.path === value.path && entry.key === value.key)) {
      list.push(value);
    }
  };

  if (catalog !== null) {
    const style = catalog.styles.find((entry) => entry.ref.id === settings.visual.art_style.id);
    if (style === undefined) {
      push(blocked, issue('unknown_catalog_id', '/visual/art_style', ISSUE_KEYS.unknownStyle));
    } else {
      const manifest = style.manifest;
      if (!manifest.themes.some((theme) => theme.id === settings.visual.theme_id)) {
        push(blocked, issue('unknown_catalog_id', '/visual/theme_id', ISSUE_KEYS.unknownTheme));
      }
      if (settings.visual.character !== null) {
        for (const slot of SLOTS) {
          const asset = settings.visual.character.slots[slot];
          if (asset !== null && hasAsset(manifest, slot, asset) === false) {
            push(blocked, issue('unknown_catalog_id', `/visual/character/slots/${slot}`, ISSUE_KEYS.unknownAsset));
          }
        }
      }
    }
    if (!catalog.layouts.some((entry) => entry.ref.id === settings.format.layout.id)) {
      push(blocked, issue('unknown_catalog_id', '/format/layout', ISSUE_KEYS.unknownLayout));
    }
    if (
      catalog.fonts !== undefined &&
      !catalog.fonts.some((font) => font.id === settings.caption.font_id.id)
    ) {
      push(blocked, issue('unknown_catalog_id', '/caption/font_id', ISSUE_KEYS.unknownFont));
    }
  }

  if (settings.caption.mode === 'typewriter' && dialogBoxFor(settings, catalog) === false) {
    push(blocked, issue('typewriter_layout', '/caption/mode', ISSUE_KEYS.typewriter));
  }
  if (settings.format.character_role === 'none' && settings.visual.character !== null) {
    push(blocked, issue('role_none_character', '/visual/character', ISSUE_KEYS.characterNone));
  }
  if (
    settings.format.character_role !== 'none' &&
    (settings.visual.character === null ||
      settings.visual.character.slots.body === null ||
      settings.visual.character.slots.face === null)
  ) {
    push(blocked, issue('character_missing', '/visual/character', ISSUE_KEYS.characterMissing));
  }
  if (
    settings.format.layout.id === 'fixed_stage' &&
    settings.format.story_structure === 'hypothetical'
  ) {
    push(warnings, issue('invalid_combination', '/format/layout', ISSUE_KEYS.weak));
  }
  if (
    settings.format.layout.id === 'fixed_stage' &&
    settings.format.character_role === 'subject'
  ) {
    push(warnings, issue('invalid_combination', '/format/layout', ISSUE_KEYS.weak));
  }

  return { blocked, warnings, ok: blocked.length === 0 };
}

export interface ChatProposal {
  ops: SetOp[];
  unsupported: string[];
}

interface ProposalGroup {
  ops: SetOp[];
  reason: string;
}

function setOp(path: string, value: unknown, origin: Origin): SetOp {
  return { op: 'set', path, value, origin };
}

function collectGroup(
  settings: Settings,
  path: string,
  value: unknown,
  catalog: ConceptCatalog | null,
): ProposalGroup | null {
  const result = changeConceptValue(settings, path, value, catalog);
  if (result.kind === 'invalid') {
    return null;
  }
  if (result.kind === 'replacement') {
    return {
      ops: result.ops.map((op) => ({ ...op, origin: 'user' })),
      reason: ISSUE_KEYS.unknownAsset,
    };
  }
  const ops = result.editedPaths.map((edited) =>
    setOp(edited, getSettingsValue(result.settings, edited), 'user'),
  );
  if (ops.length === 0) {
    ops.push(setOp(path, getSettingsValue(result.settings, path), 'user'));
  }
  return { ops, reason: ISSUE_KEYS.invalid };
}

/** Detects a prompt that asks for a new or changed drawing style. */
export function isStyleInstruction(text: string): boolean {
  const value = text.toLowerCase();
  const styleWords = /(눈|머리|옷|얼굴|색감|색을|그림체|스타일|style|eyes?|hair|outfit|color|palette|shape)/u;
  const otherValues = /(카드|이야기|자막|길이|말투|유머|농담|진행자|인물|장면|layout|duration|register|humor|role|story)/u;
  return styleWords.test(value) && !otherValues.test(value);
}

/**
 * Turns a chat sentence into typed settings ops. Each directive is validated
 * against the values already accepted, so an impossible combination never
 * reaches a plan.
 */
export function chatProposal(
  settings: Settings,
  text: string,
  catalog: ConceptCatalog | null,
): ChatProposal {
  const value = text.toLowerCase();
  let candidate = cloneSettings(settings);
  const accepted: SetOp[] = [];
  const unsupported: string[] = [];

  const addGroup = (path: string, nextValue: unknown): void => {
    const group = collectGroup(candidate, path, nextValue, catalog);
    if (group === null) {
      unsupported.push(ISSUE_KEYS.invalid);
      return;
    }
    const applied = applySettingsOps(candidate, group.ops);
    const validation = validateConcept(applied, catalog);
    if (!validation.ok) {
      unsupported.push(validation.blocked[0].key);
      return;
    }
    candidate = applied;
    accepted.push(...group.ops);
  };

  if (/(진행자|presenter|해설)/u.test(value)) {
    addGroup('/format/character_role', 'presenter');
  } else if (/(캐릭터\s*없|주인공\s*없|no character|without character)/u.test(value)) {
    addGroup('/format/character_role', 'none');
  } else if (/(인물|주인공|subject|등장인물)/u.test(value)) {
    addGroup('/format/character_role', 'subject');
  }

  if (/(만약|what if|hypothetical)/u.test(value)) {
    addGroup('/format/story_structure', 'hypothetical');
  } else if (/(비유|○○|analogy|it'?s like)/u.test(value)) {
    addGroup('/format/story_structure', 'single_analogy');
  } else if (/(딱\s*3|세\s*가지|3가지|just three|numbered)/u.test(value)) {
    addGroup('/format/story_structure', 'numbered_three');
  }

  if (/(대화창|대화\s*무대|dialog)/u.test(value)) {
    addGroup('/format/layout', 'dialog_stage');
  } else if (/(장면\s*중심|full\s*stage|풀\s*스테이지)/u.test(value)) {
    addGroup('/format/layout', 'full_stage');
  } else if (/(고정\s*무대|fixed\s*stage)/u.test(value)) {
    addGroup('/format/layout', 'fixed_stage');
  }

  if (/(타자기|typewriter)/u.test(value)) {
    addGroup('/caption/mode', 'typewriter');
  } else if (/(구절|phrase)/u.test(value)) {
    addGroup('/caption/mode', 'phrase');
  } else if (/(문장형|sentence)/u.test(value)) {
    addGroup('/caption/mode', 'sentence');
  }

  if (/(반말|캐주얼|casual)/u.test(value)) {
    addGroup('/format/register', 'casual');
  } else if (/(친근|friendly)/u.test(value)) {
    addGroup('/format/register', 'friendly');
  } else if (/(설명체|중립|차분|neutral|calm)/u.test(value)) {
    addGroup('/format/register', 'neutral');
  }

  if (/(농담\s*빼|농담\s*없|진지|담백|no humor|serious)/u.test(value)) {
    addGroup('/format/humor', 'none');
  } else if (/(유머|재미|농담|humor|funny)/u.test(value)) {
    addGroup('/format/humor', 'light');
  }

  if (/(페이드|fade)/u.test(value)) {
    addGroup('/motion/transition', 'fade');
  } else if (/(컷|cut)/u.test(value)) {
    addGroup('/motion/transition', 'cut');
  }

  if (/(2분|120초|120s)/u.test(value)) {
    addGroup('/target_duration_s', 120);
  } else if (/(1분|60초|60s)/u.test(value)) {
    addGroup('/target_duration_s', 60);
  } else if (/(30초|30s)/u.test(value)) {
    addGroup('/target_duration_s', 30);
  }

  const sceneMatch = value.match(/장면\s*(\d+)/u);
  if (sceneMatch !== null) {
    addGroup('/format/scene_count', Number(sceneMatch[1]));
  }

  if (/(픽셀|pixel)/u.test(value)) {
    addGroup('/visual/art_style', PIXEL_REF);
  } else if (/(그림체|스타일|style)/u.test(value)) {
    unsupported.push(ISSUE_KEYS.unknownStyle);
  }

  const ops = new Map<string, SetOp>();
  for (const op of accepted) {
    ops.set(op.path, op);
  }
  if (ops.size === 0 && unsupported.length === 0) {
    unsupported.push(ISSUE_KEYS.invalid);
  }
  return { ops: [...ops.values()], unsupported };
}

/** Reference analysis proposes a small, deterministic set of format values. */
export function referenceProposal(
  settings: Settings,
  catalog: ConceptCatalog | null,
): ChatProposal {
  let candidate = cloneSettings(settings);
  const accepted: SetOp[] = [];
  const unsupported: string[] = [];
  const proposals: { path: string; value: unknown }[] = [
    { path: '/format/story_structure', value: 'single_analogy' },
    { path: '/format/layout', value: LAYOUT_REFS.full_stage },
    { path: '/caption/mode', value: 'phrase' },
    { path: '/format/humor', value: 'light' },
  ];

  for (const proposal of proposals) {
    const current = getSettingsValue(candidate, proposal.path);
    if (JSON.stringify(current) === JSON.stringify(proposal.value)) {
      continue;
    }
    const group = collectGroup(candidate, proposal.path, proposal.value, catalog);
    if (group === null) {
      unsupported.push(ISSUE_KEYS.invalid);
      continue;
    }
    const ops = group.ops.map((op) => ({ ...op, origin: 'reference' as const }));
    const applied = applySettingsOps(candidate, ops);
    const validation = validateConcept(applied, catalog);
    if (!validation.ok) {
      unsupported.push(validation.blocked[0].key);
      continue;
    }
    candidate = applied;
    accepted.push(...ops);
  }
  return { ops: accepted, unsupported };
}

export interface PlanImpact {
  requiresConfirmation: boolean;
  reasons: Plan['confirmation_reasons'];
  lockedKeys: LockKey[];
  overwrites: string[];
  warnings: Plan['warnings'];
}

/** Compares a plan with the current settings to describe confirmation needs. */
export function planImpact(
  settings: Settings,
  ops: readonly SetOp[],
  source: 'direct' | 'card' | 'chat' | 'reference' | 'style' | 'template' | 'bgm' | 'scene_rewrite',
): PlanImpact {
  const candidate = applySettingsOps(settings, ops);
  const changed = ops.filter(
    (op) => JSON.stringify(getSettingsValue(settings, op.path)) !== JSON.stringify(getSettingsValue(candidate, op.path)),
  );
  const reasons = new Set<Plan['confirmation_reasons'][number]>();
  const locked = new Set<LockKey>();
  const overwrites: string[] = [];

  for (const op of changed) {
    const origin = originOf(settings, op.path);
    if (origin === 'user' && (source !== 'chat' || op.origin !== 'user')) {
      reasons.add('user_value_overwrite');
      overwrites.push(op.path);
    }
    const key = lockKeyForPath(op.path);
    if (key !== null && settings.locks[key] === 'locked') {
      reasons.add('lock_change');
      locked.add(key);
    }
    if (op.path === '/visual/art_style') {
      reasons.add('rebuild_render');
    }
  }
  const validation = validateConcept(candidate, null);
  const warnings: Plan['warnings'] = validation.warnings.length === 0
    ? []
    : [{ code: 'weak_combination', scene_id: null }];

  const requiresConfirmation = reasons.size > 0 || changed.length > 1;
  return {
    requiresConfirmation,
    reasons: [...reasons],
    lockedKeys: [...locked],
    overwrites,
    warnings,
  };
}
