import { useSyncExternalStore } from 'react';

import {
  MAX_TEXT_ATTACHMENTS,
  readTextFile,
} from './attachments';
import {
  CONCEPT_LOCK_KEYS,
  applySettingsOps,
  cardIdForSettings,
  cardTuneOf,
  cardTunePreset,
  changeCard,
  changeCardTune,
  changeConceptValue,
  cloneSettings,
  getSettingsValue,
  isConceptLockedPath,
  isStyleInstruction,
  normalizePointer,
  originPath,
  planImpact,
  planTouchesLockedFields,
  resetConceptValue,
  SLOTS,
  validateConcept,
  withSettingsValue,
  type ChangeResult,
  type ValidationIssue,
} from './model';
import {
  ConceptApiError,
  createMockConceptApi,
  MockConceptApi,
  ORIGIN_PATHS,
  type ConceptApi,
  type ConceptStartInput,
} from './api';
import type {
  Attachment,
  CardTune,
  ConceptCatalog,
  ConceptChange,
  ConceptDocument,
  ConceptForget,
  ConceptJob,
  ConceptReadState,
  ConceptSnapshot,
  LockKey,
  Plan,
  Settings,
  SetOp,
} from './types';

const ERROR_INVALID = 'concept.error.invalidCombination';
const NOTICE_PICK_DROPPED = 'concept.reason.user_value_overwrite';
const ERROR_LOCKED = 'concept.error.conceptLocked';
const ERROR_CATALOG = 'concept.error.catalog';
const ERROR_STALE = 'concept.error.stale';
const ERROR_PENDING = 'concept.error.pendingPlan';
const ERROR_APPLIED = 'concept.error.planApplied';
const ERROR_MATERIAL = 'concept.error.materialLimit';
const ERROR_EMPTY = 'concept.error.emptyMessage';
const ERROR_JOB = 'concept.error.jobFailed';
const ERROR_NO_SESSION = 'concept.error.noSession';
const ERROR_BUSY = 'concept.error.busy';
const ERROR_SAVE = 'concept.error.saveFailed';
const ERROR_STYLE_ATTACHMENT = 'concept.error.styleAttachment';

/** Plan sources whose values the screen may mark as set by the draft or a chat. */
const ASSISTANT_PLAN_SOURCES: Readonly<Partial<Record<Plan['source'], true>>> = {
  chat: true,
  reference: true,
  style: true,
};

const LOCAL_PLAN_PREFIX = 'local_plan_';
const MAX_POLLS = 20;

interface EditRecord {
  path: string;
  generation: number;
}

interface SessionState {
  document: ConceptDocument;
  catalog: ConceptCatalog | null;
  loading: boolean;
  busy: number;
  error: string | null;
  pending: Plan | null;
  notes: string[];
  unsupported: string[];
  jobs: ConceptJob[];
  draft: string;
  undo: Settings[];
  dirty: boolean;
  editGeneration: number;
  edits: EditRecord[];
  catalogRequest: number;
  applyingPlanId: string | null;
  cardTunes: Record<string, CardTune>;
  opening: Settings;
  /** Whether the first post-draft read recorded the opening reply values. */
  openingRead: boolean;
  /** Whether this video's draft was applied and the document read. */
  readState: ConceptReadState;
  /** The draft result for this video, kept so a retry cannot change it. */
  readApplied: boolean;
  /** The read's own error, cleared only by a successful concept read. */
  readError: string | null;
  /** Set when a direct pick the draft's art style cannot use was dropped. */
  readNotice: string | null;
  /** Paths the draft or a chat set, until the screen has shown them once. */
  changedPaths: ConceptChange[];
  /** Per-path change counts, kept after a mark is shown so a repeat flips. */
  changeVersions: Record<string, number>;
  /** The latest invalidation delivered to the screen. */
  forgotten: ConceptForget | null;
  forgetVersion: number;
}

let api: ConceptApi = createMockConceptApi();
let sessions = new Map<string, SessionState>();
let activeId: string | null = null;
let epoch = 0;
let startToken = 0;
let localPlanSequence = 0;
const listeners = new Set<() => void>();
let cachedSnapshot: ConceptSnapshot | null = null;
let cacheDirty = true;

function notice(session: SessionState, ko: string, en: string): string {
  return session.document.settings.language === 'ko' ? ko : en;
}

function localizedIssue(session: SessionState, key: string): string {
  const messages: Record<string, { ko: string; en: string }> = {
    'concept.reason.characterNoneWithParts': {
      ko: '캐릭터를 쓰지 않기로 한 설정과 부위가 맞지 않아요.',
      en: 'The selected character parts need a character role.',
    },
    'concept.reason.characterMissing': {
      ko: '이 역할에는 캐릭터 몸과 얼굴이 필요해요.',
      en: 'This role needs a character body and face.',
    },
    'concept.reason.typewriterNeedsDialog': {
      ko: '타자기 자막은 대화창 화면 구성에서만 쓸 수 있어요.',
      en: 'Typewriter captions need a dialog-stage layout.',
    },
    'concept.reason.unknownAsset': {
      ko: '이 그림체에 없는 부위가 있어 대체안을 확인해야 해요.',
      en: 'This style lacks some selected parts; review the replacements.',
    },
    'concept.reason.weakCombination': {
      ko: '이 조합은 가능하지만 어울리지 않을 수 있어요.',
      en: 'This combination works but may not fit well.',
    },
  };
  return notice(
    session,
    messages[key]?.ko ?? key,
    messages[key]?.en ?? key,
  );
}

function setError(session: SessionState, key: string | null): void {
  session.error = key;
}

function clearError(session: SessionState): void {
  if (session.error !== ERROR_CATALOG) {
    session.error = null;
  }
}

function emit(): void {
  cacheDirty = true;
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function buildSnapshot(): ConceptSnapshot | null {
  const session = activeId === null ? null : sessions.get(activeId) ?? null;
  if (session === null) {
    return null;
  }
  const job = session.jobs.at(-1) ?? null;
  const jobActive = session.jobs.some(
    (entry) => entry.state === 'queued' || entry.state === 'running',
  );
  return {
    document: session.document,
    catalog: session.catalog,
    loading: session.loading,
    busy: session.busy > 0 || jobActive,
    error: session.error,
    pending: session.pending,
    notes: session.notes,
    unsupported: session.unsupported,
    job,
    draft: session.draft,
    canUndo: session.undo.length > 0,
    cardTunes: session.cardTunes,
    opening: session.opening,
    readState: session.readState,
    readError: session.readError,
    readNotice: session.readNotice,
    changedPaths: session.changedPaths,
    forgotten: session.forgotten,
  };
}

function readSnapshot(): ConceptSnapshot | null {
  if (cacheDirty) {
    cachedSnapshot = buildSnapshot();
    cacheDirty = false;
  }
  return cachedSnapshot;
}

export function getConceptSnapshot(): ConceptSnapshot | null {
  return readSnapshot();
}

export function useConcept(): ConceptSnapshot | null {
  return useSyncExternalStore(subscribe, readSnapshot, readSnapshot);
}

/** Clears the changed marks once the screen has shown them, so a remount does not replay. */
export function acknowledgeConceptChanged(): void {
  const session = activeSession();
  if (session === null || session.changedPaths.length === 0) {
    return;
  }
  session.changedPaths = [];
  emit();
}

function createSession(document: ConceptDocument): SessionState {
  return {
    document,
    catalog: null,
    loading: false,
    busy: 0,
    error: null,
    pending: null,
    notes: [],
    unsupported: [],
    jobs: [],
    draft: '',
    undo: [],
    dirty: false,
    editGeneration: 0,
    edits: [],
    catalogRequest: 0,
    applyingPlanId: null,
    cardTunes: {},
    opening: cloneSettings(document.settings),
    openingRead: false,
    readState: 'idle',
    readApplied: true,
    readError: null,
    readNotice: null,
    changedPaths: [],
    changeVersions: {},
    forgotten: null,
    forgetVersion: 0,
  };
}

function activeSession(): SessionState | null {
  return activeId === null ? null : sessions.get(activeId) ?? null;
}

function requireSession(): SessionState {
  const session = activeSession();
  if (session === null) {
    throw new Error(ERROR_NO_SESSION);
  }
  return session;
}

function markEdited(session: SessionState, paths: readonly string[]): void {
  if (paths.length === 0) {
    return;
  }
  session.editGeneration += 1;
  for (const path of paths) {
    session.edits.push({ path, generation: session.editGeneration });
  }
}

function editedSince(session: SessionState, generation: number): Set<string> {
  return new Set(
    session.edits
      .filter((entry) => entry.generation > generation)
      .map((entry) => entry.path),
  );
}

function editedAfter(session: SessionState, generation: number): boolean {
  return session.editGeneration > generation;
}

/** Records the paths the draft or a chat set, for the one-time changed mark. */
function markChanged(session: SessionState, paths: readonly string[]): void {
  const unique = [...new Set(paths)];
  if (unique.length === 0) {
    return;
  }
  let next = session.changedPaths;
  for (const path of unique) {
    const version = (session.changeVersions[path] ?? 0) + 1;
    session.changeVersions[path] = version;
    next = [...next.filter((entry) => entry.path !== path), { path, version }];
  }
  session.changedPaths = next;
}

/** Whether a changed mark at `mark` covers `path` or sits under it. */
export function conceptPathTouches(mark: string, path: string): boolean {
  return mark === path || path.startsWith(`${mark}/`) || mark.startsWith(`${path}/`);
}

/** A user pick supersedes the draft's mark for the same value. */
function forgetChanged(session: SessionState, paths: readonly string[]): void {
  session.changedPaths = session.changedPaths.filter(
    (entry) => !paths.some((path) => conceptPathTouches(entry.path, path)),
  );
  session.forgetVersion += 1;
  session.forgotten = { paths: [...paths], version: session.forgetVersion };
}

function pushUndo(session: SessionState): void {
  session.undo = [cloneSettings(session.document.settings)];
}

function sameSettings(left: Settings, right: Settings): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Settings objects that change as one value, never member by member. */
const WHOLE_VALUE_PATHS = new Set([
  '/format/layout',
  '/visual/art_style',
  '/caption/font_id',
  '/visual/theme_id',
  '/audio/voice',
  '/audio/bgm',
  '/caption/typing_sound',
  '/caption/extra',
  '/extra_instructions',
]);

/** The settings paths whose values actually differ; character slots stay separate. */
function changedValuePaths(before: Settings, after: Settings): string[] {
  const paths: string[] = [];
  const walk = (prefix: string, left: unknown, right: unknown): void => {
    if (JSON.stringify(left) === JSON.stringify(right)) return;
    if (prefix === '/visual/character') {
      const leftSlots = isRecord(left) && isRecord(left.slots) ? left.slots : {};
      const rightSlots = isRecord(right) && isRecord(right.slots) ? right.slots : {};
      for (const slot of SLOTS) {
        if (JSON.stringify(leftSlots[slot] ?? null) !== JSON.stringify(rightSlots[slot] ?? null)) {
          paths.push(`/visual/character/slots/${slot}`);
        }
      }
      return;
    }
    if (isRecord(left) && isRecord(right) && !WHOLE_VALUE_PATHS.has(prefix)) {
      for (const key of new Set([...Object.keys(left), ...Object.keys(right)])) {
        if (prefix === '' && (key === 'origins' || key === 'locks')) continue;
        walk(`${prefix}/${key}`, left[key], right[key]);
      }
      return;
    }
    if (prefix !== '') paths.push(prefix);
  };
  walk('', before, after);
  return paths;
}

/** The edited paths minus the picks the loaded art style cannot use. */
function withoutUnfitPicks(
  edited: ReadonlySet<string>,
  blocked: readonly ValidationIssue[],
): Set<string> {
  const next = new Set(edited);
  for (const issue of blocked) {
    if (issue.code !== 'unknown_catalog_id') continue;
    for (const path of [...next]) {
      if (!conceptPathTouches(path, issue.path)) continue;
      next.delete(path);
      // A whole-character pick keeps the slots that are not the unfit one.
      if (path === '/visual/character' && issue.path !== path) {
        for (const slot of SLOTS) {
          const slotPath = `/visual/character/slots/${slot}`;
          if (slotPath !== issue.path) next.add(slotPath);
        }
      }
    }
  }
  return next;
}

/** The edited paths plus the other side of only the validity pairs that failed. */
function withFailingPairs(
  edited: ReadonlySet<string>,
  blocked: readonly ValidationIssue[],
): Set<string> {
  const next = new Set(edited);
  const add = (left: string, right: string): void => {
    const leftEdited = [...edited].some((path) => conceptPathTouches(path, left));
    const rightEdited = [...edited].some((path) => conceptPathTouches(path, right));
    if (leftEdited && !rightEdited) next.add(right);
    if (rightEdited && !leftEdited) next.add(left);
  };
  for (const issue of blocked) {
    if (issue.code === 'typewriter_layout' || issue.path === '/caption/mode' || issue.path === '/format/layout') {
      add('/format/layout', '/caption/mode');
    } else if (
      issue.path === '/format/character_role' ||
      issue.path === '/visual/character' ||
      issue.path.startsWith('/visual/character/')
    ) {
      add('/format/character_role', '/visual/character');
    }
  }
  return next;
}

/** Whether a plan op touches a value the user already changed on this screen. */
function editConflicts(edited: ReadonlySet<string>, path: string): boolean {
  if (edited.has('*')) return true;
  return [...edited].some((entry) => conceptPathTouches(entry, path));
}

/** The loaded document with the paths the screen changed kept from its copy. */
function mergeEditedSettings(loaded: Settings, current: Settings, edited: ReadonlySet<string>): Settings {
  if (edited.has('*')) {
    return cloneSettings(current);
  }
  let merged = cloneSettings(loaded);
  for (const path of edited) {
    const pointer = normalizePointer(path);
    if (pointer === null) continue;
    const value = getSettingsValue(current, pointer);
    if (value === undefined) continue;
    merged = withSettingsValue(merged, pointer, value);
    const origin = current.origins[pointer] ?? current.origins[originPath(pointer)] ?? 'user';
    merged.origins[pointer] = origin;
    const aggregate = originPath(pointer);
    if (aggregate !== pointer) merged.origins[aggregate] = origin;
  }
  return merged;
}

function sendError(error: unknown, fallback: string): string {
  if (error instanceof ConceptApiError) {
    if (error.code === 'material_limit') {
      return ERROR_MATERIAL;
    }
    if (error.code === 'concept_locked') {
      return ERROR_LOCKED;
    }
    if (error.code === 'change_stale') {
      return ERROR_STALE;
    }
    if (error.code === 'invalid_combination') {
      return ERROR_INVALID;
    }
    if (error.code === 'revision_conflict') {
      return ERROR_STALE;
    }
    if (error.code === 'not_found') {
      return ERROR_NO_SESSION;
    }
  }
  return fallback;
}

function setPlanOps(plan: Plan): SetOp[] {
  return plan.ops.filter((op): op is SetOp => op.op === 'set');
}

/** The display paths an applied set of ops actually changed, character slots split. */
function changedOpPaths(before: Settings, after: Settings, ops: readonly SetOp[]): string[] {
  const paths = new Set<string>();
  for (const op of ops) {
    if (op.path === '/visual/character') {
      for (const slot of SLOTS) {
        const path = `/visual/character/slots/${slot}`;
        if (JSON.stringify(getSettingsValue(before, path)) !== JSON.stringify(getSettingsValue(after, path))) {
          paths.add(path);
        }
      }
    } else if (JSON.stringify(getSettingsValue(before, op.path)) !== JSON.stringify(getSettingsValue(after, op.path))) {
      paths.add(op.path);
    }
  }
  return [...paths];
}

function makeLocalPlan(
  session: SessionState,
  ops: readonly SetOp[],
  notes: string[],
): Plan {
  const impact = planImpact(session.document.settings, ops, 'direct');
  localPlanSequence += 1;
  return {
    schema_version: 2,
    id: `${LOCAL_PLAN_PREFIX}${localPlanSequence}`,
    video_id: session.document.id,
    base_revision: session.document.revision,
    applied_revision: null,
    status: 'proposed',
    source: 'direct',
    target: { scene_id: null, pointer: null },
    ops: [...ops],
    effects: {
      script: false,
      scene_ids_text: [],
      scene_ids_tts: [],
      scene_ids_render: [],
      mix: false,
      assemble: false,
      locked_keys: impact.lockedKeys,
      overwrites_user_values: impact.overwrites,
    },
    requires_confirmation: true,
    confirmation_reasons: impact.reasons,
    warnings: impact.warnings,
    notes,
    unsupported: [],
    created_at: '2026-01-01T00:00:00Z',
  };
}

function openReplacementPlan(session: SessionState, ops: readonly SetOp[]): void {
  const notes = [
    notice(
      session,
      '지금 고른 부위가 이 그림체에 없어요. 대체안을 확인한 뒤 적용하세요.',
      'Some selected parts are missing from this style. Review the replacements before applying.',
    ),
  ];
  session.pending = makeLocalPlan(session, ops, notes);
  session.notes = notes;
  session.unsupported = [];
  clearError(session);
  emit();
}

function commitChange(
  session: SessionState,
  result: ChangeResult,
): string[] {
  if (result.kind === 'invalid') {
    setError(session, ERROR_INVALID);
    emit();
    return [];
  }
  if (result.kind === 'replacement') {
    openReplacementPlan(session, result.ops);
    return [];
  }
  const before = session.document.settings;
  if (sameSettings(result.settings, before)) {
    clearError(session);
    emit();
    return [];
  }
  const changed = changedValuePaths(before, result.settings);
  pushUndo(session);
  session.document = { ...session.document, settings: result.settings };
  session.dirty = true;
  forgetChanged(session, changed);
  markEdited(session, changed);
  clearError(session);
  emit();
  return changed;
}

/**
 * The picked story card shows from the first paint. A server that opens the
 * video before the draft has written it answers with the default card, so the
 * card the user chose is applied to the opening view here; the read after the
 * draft replaces it with what the server wrote.
 */
function withPickedCard(created: ConceptDocument, input: ConceptStartInput): ConceptDocument {
  const cardId = input.cardId ?? null;
  if (cardId === null || cardIdForSettings(created.settings) === cardId) {
    return created;
  }
  const picked = changeCard(created.settings, cardId, input.duration ?? created.settings.target_duration_s, null);
  return picked.kind === 'changed' ? { ...created, settings: picked.settings } : created;
}

export async function beginConcept(input: ConceptStartInput): Promise<ConceptDocument | null> {
  const token = ++startToken;
  const currentEpoch = epoch;
  const created = await api.create(input);
  if (currentEpoch !== epoch) {
    return null;
  }
  const session = createSession(withPickedCard(created, input));
  sessions.set(created.id, session);
  if (token !== startToken) {
    return null;
  }
  activeId = created.id;
  emit();
  void loadCatalog(session).catch(() => undefined);

  await startExtras(session, input.attachments ?? []);
  return created;
}

async function startExtras(session: SessionState, attachments: readonly Attachment[]): Promise<void> {
  const extras = attachments.filter((attachment) => attachment.kind !== 'text');
  if (extras.length === 0) {
    return;
  }
  try {
    const job = await api.message(session.document.id, '', extras);
    void runJob(session, job, session.editGeneration).catch((error: unknown) => {
      if (sessions.get(session.document.id) === session) {
        setError(session, sendError(error, ERROR_JOB));
        emit();
      }
    });
  } catch (error) {
    if (sessions.get(session.document.id) === session) {
      setError(session, sendError(error, ERROR_JOB));
      emit();
    }
    throw error;
  }
}

/** Starts the files and links the first screen held back until the draft was written. */
export async function attachConceptExtras(attachments: readonly Attachment[]): Promise<void> {
  const session = activeSession();
  if (session !== null) {
    await startExtras(session, attachments);
  }
}

/**
 * Reads the video again after a job outside this screen changed it. The
 * revision and the stored materials follow the server; settings the user has
 * changed are kept, and the rest follow the server too. A failed read keeps
 * the session as it is and shows the error instead of throwing.
 *
 * `applied` says the draft wrote its values; a proposed or cancelled draft is
 * read for the screen but never becomes the first reply. Returns whether the
 * read succeeded, so the caller can stop its writing state.
 */
export async function reloadConcept(videoId: string, applied?: boolean): Promise<boolean> {
  const session = sessions.get(videoId);
  if (session === undefined) {
    return false;
  }
  if (applied !== undefined) session.readApplied = applied;
  const readApplied = session.readApplied;
  session.readState = 'waiting';
  emit();
  let loaded: ConceptDocument;
  try {
    loaded = await api.load(videoId);
  } catch (error) {
    // The materials the user added stay in the session and the caller goes on
    // with the files and links it held back; the screen says the read failed.
    if (sessions.get(videoId) === session) {
      session.readError = sendError(error, ERROR_JOB);
      session.readState = 'failed';
      emit();
    }
    return false;
  }
  if (sessions.get(videoId) !== session) {
    return false;
  }
  const previous = session.document.settings;
  const edited = new Set(session.edits.map((entry) => entry.path));
  // An edit with no recorded path (an undo) has no per-path value to merge.
  const keepAll = session.dirty && edited.size === 0;
  let mergePaths = edited;
  let candidate = keepAll
    ? cloneSettings(previous)
    : mergeEditedSettings(loaded.settings, previous, mergePaths);
  const validation = session.catalog === null ? null : validateConcept(candidate, session.catalog);
  let valid = validation === null || validation.ok;
  // Resolve each failing rule on its own field: a direct pick the draft's art
  // style cannot use goes back to the draft's value, and only the pair whose
  // own rule failed is restored together.
  let dropped = false;
  for (let round = 0; round < 4 && !valid && !keepAll && validation !== null; round += 1) {
    const blocked = validateConcept(candidate, session.catalog as ConceptCatalog).blocked;
    const unfit = withoutUnfitPicks(mergePaths, blocked);
    const paired = withFailingPairs(unfit, blocked);
    if (unfit.size !== mergePaths.size || [...unfit].some((path) => !mergePaths.has(path))) dropped = true;
    if (paired.size === mergePaths.size && [...paired].every((path) => mergePaths.has(path))) break;
    mergePaths = paired;
    candidate = mergeEditedSettings(loaded.settings, previous, mergePaths);
    valid = validateConcept(candidate, session.catalog as ConceptCatalog).ok;
  }
  // Never show a combination the confirm step would reject; the user's own
  // valid state stays on screen instead.
  const merged = valid ? candidate : cloneSettings(previous);
  // The first read after the draft names what the draft picked, even when a
  // direct pick during the draft keeps its own value on the screen. Later
  // reads keep the first reply frozen.
  const firstRead = readApplied && !session.openingRead;
  if (firstRead) {
    session.opening = cloneSettings(loaded.settings);
  }
  const changed = firstRead
    ? changedValuePaths(previous, merged).filter((path) => !editConflicts(mergePaths, path))
    : [];
  if (firstRead) {
    session.changedPaths = [];
    markChanged(session, changed);
    session.openingRead = true;
  }
  session.readError = valid ? null : ERROR_INVALID;
  session.readNotice = valid && dropped ? NOTICE_PICK_DROPPED : null;
  session.readState = readApplied && valid ? 'ready' : 'failed';
  session.document = {
    ...loaded,
    settings: merged,
    attachments: appendAttachments(loaded.attachments, session.document.attachments.filter((entry) => entry.kind !== 'text')),
  };
  session.dirty = mergePaths.size > 0 || keepAll;
  emit();
  return true;
}

/**
 * Opens a default session when entering the concept step without one. The
 * mock create call settles immediately, so callers can read the snapshot on
 * the next microtask.
 */
export function ensureConcept(): void {
  if (activeId !== null) {
    return;
  }
  if (sessions.size > 0) {
    const [first] = sessions.values();
    activeId = first.document.id;
    if (first.catalog === null && !first.loading) {
      void loadCatalog(first).catch(() => undefined);
    }
    emit();
    return;
  }
  void beginConcept({ topic: '새 영상' }).catch((error: unknown) => {
    const session = activeSession();
    if (session !== null) {
      setError(session, sendError(error, ERROR_SAVE));
      emit();
    }
  });
}

export function setConceptDraft(value: string): void {
  const session = activeSession();
  if (session === null) {
    return;
  }
  session.draft = value;
  emit();
}

/**
 * The concept step's 「그림체 말로 만들기」 lives in the conversation box's menu,
 * so the art-style row keeps the canon's shape. The count carries each request
 * to the screen, which owns the entry window.
 */
let styleEntryRequests = 0;

export function requestConceptStyleEntry(): void {
  styleEntryRequests += 1;
  emit();
}

export function useConceptStyleEntry(): number {
  return useSyncExternalStore(subscribe, () => styleEntryRequests, () => styleEntryRequests);
}

export async function sendConcept(
  text: string,
  attachments: Attachment[] = [],
): Promise<void> {
  const session = requireSession();
  const trimmed = text.trim();
  if (trimmed === '' && attachments.length === 0) {
    setError(session, ERROR_EMPTY);
    emit();
    throw new Error(ERROR_EMPTY);
  }
  const materialCount = textMaterialCount(session.document.attachments, attachments);
  if (materialCount > MAX_TEXT_ATTACHMENTS) {
    setError(session, ERROR_MATERIAL);
    emit();
    throw new Error(ERROR_MATERIAL);
  }
  const generation = session.editGeneration;

  if (trimmed !== '' && isStyleInstruction(trimmed)) {
    const references = attachments.filter(
      (attachment) => attachment.kind === 'reference' || attachment.kind === 'link',
    );
    const other = attachments.filter(
      (attachment) => attachment.kind !== 'reference' && attachment.kind !== 'link',
    );
    if (other.length > 0 || references.length > 1) {
      setError(session, ERROR_STYLE_ATTACHMENT);
      emit();
      throw new Error(ERROR_STYLE_ATTACHMENT);
    }
    await createConceptStyle(trimmed, references[0]);
    session.draft = '';
    emit();
    return;
  }

  const hydrated = await hydrateTextAttachments(attachments).catch((error: unknown) => {
    setError(session, ERROR_SAVE);
    emit();
    throw error;
  });
  session.busy += 1;
  emit();
  try {
    if (session.dirty) await saveSelections(session);
    const job = await api.message(session.document.id, text, hydrated);
    await runJob(session, job, generation, hydrated);
    session.draft = '';
  } catch (error) {
    if (sessions.get(session.document.id) === session) {
      setError(session, sendError(error, ERROR_JOB));
      emit();
    }
    throw error;
  } finally {
    session.busy = Math.max(0, session.busy - 1);
    emit();
  }
}

export function chooseConcept(path: string, value: unknown): string[] {
  const session = activeSession();
  if (session === null) {
    return [];
  }
  const pointer = normalizePointer(path);
  if (pointer !== null && session.document.confirmed && isConceptLockedPath(pointer)) {
    setError(session, ERROR_LOCKED);
    emit();
    return [];
  }
  const result = changeConceptValue(session.document.settings, path, value, session.catalog);
  return commitChange(session, result);
}

/**
 * Select a story card with the four values shown in its fine-tune panel.
 * The values of the card being left stay with the video session, so a step
 * change does not reset them, and the card being entered gets its own values.
 */
export function chooseCardTune(id: string): string[] {
  const session = activeSession();
  if (session === null) {
    return [];
  }
  if (session.document.confirmed) {
    setError(session, ERROR_LOCKED);
    emit();
    return [];
  }
  const settings = session.document.settings;
  const active = cardIdForSettings(settings);
  if (active === id) {
    return [];
  }
  const tune = session.cardTunes[id] ?? cardTunePreset(id, session.catalog);
  if (tune === null) {
    setError(session, ERROR_INVALID);
    emit();
    return [];
  }
  const result = changeCardTune(
    settings,
    id,
    tune,
    settings.target_duration_s,
    session.catalog,
  );
  if (result.kind === 'changed' && active !== null) {
    session.cardTunes[active] = cardTuneOf(settings);
  }
  return commitChange(session, result);
}

export function resetConcept(path: string): string[] {
  const session = activeSession();
  if (session === null) {
    return [];
  }
  const pointer = normalizePointer(path);
  if (pointer !== null && session.document.confirmed && isConceptLockedPath(pointer)) {
    setError(session, ERROR_LOCKED);
    emit();
    return [];
  }
  const result = resetConceptValue(session.document.settings, path, session.catalog);
  return commitChange(session, result);
}

/** Dismisses only the mark versions a detail panel actually showed. */
export function consumeConceptChanged(videoId: string, entries: readonly ConceptChange[]): void {
  if (entries.length === 0) {
    return;
  }
  const session = sessions.get(videoId);
  if (session === undefined) {
    return;
  }
  const changes = [...new Map(entries.map((entry) => [entry.path, entry.version])).entries()]
    .map(([path, version]) => ({ path, version }));
  session.changedPaths = session.changedPaths.filter(
    (entry) => !changes.some((change) => change.path === entry.path && change.version === entry.version),
  );
  session.forgetVersion += 1;
  session.forgotten = { paths: changes.map((change) => change.path), changes, version: session.forgetVersion };
  emit();
}

export function toggleConceptLock(key: LockKey): void {
  const session = activeSession();
  if (session === null) {
    return;
  }
  if (!CONCEPT_LOCK_KEYS.includes(key)) {
    setError(session, ERROR_INVALID);
    emit();
    return;
  }
  pushUndo(session);
  const settings = cloneSettings(session.document.settings);
  settings.locks[key] = settings.locks[key] === 'locked' ? 'varied' : 'locked';
  session.document = { ...session.document, settings };
  session.dirty = true;
  markEdited(session, [`/locks/${key}`]);
  clearError(session);
  emit();
}

export function undoConcept(): void {
  const session = activeSession();
  if (session === null || session.undo.length === 0) {
    return;
  }
  const settings = session.undo.pop();
  if (settings === undefined) {
    return;
  }
  const before = session.document.settings;
  session.document = { ...session.document, settings };
  session.dirty = true;
  markEdited(session, ['*']);
  forgetChanged(session, ORIGIN_PATHS.filter((path) =>
    JSON.stringify(getSettingsValue(before, path)) !== JSON.stringify(getSettingsValue(settings, path))));
  clearError(session);
  emit();
}

export async function applyConceptPlan(): Promise<void> {
  const session = requireSession();
  const plan = session.pending;
  if (plan === null) {
    setError(session, ERROR_APPLIED);
    emit();
    throw new Error(ERROR_APPLIED);
  }
  if (plan.status !== 'proposed') {
    setError(session, plan.status === 'stale' ? ERROR_STALE : ERROR_APPLIED);
    emit();
    throw new Error(plan.status === 'stale' ? ERROR_STALE : ERROR_APPLIED);
  }
  if (plan.base_revision !== session.document.revision) {
    session.pending = { ...plan, status: 'stale' };
    setError(session, ERROR_STALE);
    emit();
    throw new Error(ERROR_STALE);
  }
  const ops = setPlanOps(plan);
  if (session.document.confirmed && planTouchesLockedFields(ops)) {
    setError(session, ERROR_LOCKED);
    emit();
    throw new Error(ERROR_LOCKED);
  }
  if (session.applyingPlanId !== null) {
    setError(session, ERROR_BUSY);
    emit();
    throw new Error(ERROR_BUSY);
  }
  const candidate = applySettingsOps(session.document.settings, ops);
  const validation = validateConcept(candidate, session.catalog);
  if (!validation.ok) {
    setError(session, ERROR_INVALID);
    session.unsupported = validation.blocked.map((entry) => localizedIssue(session, entry.key));
    emit();
    throw new Error(ERROR_INVALID);
  }

  session.applyingPlanId = plan.id;
  const generation = session.editGeneration;
  session.busy += 1;
  emit();
  try {
    if (plan.id.startsWith(LOCAL_PLAN_PREFIX)) {
      const saved = await api.save(session.document.id, candidate);
      if (sessions.get(session.document.id) !== session) {
        return;
      }
      const before = session.document.settings;
      pushUndo(session);
      if (editedAfter(session, generation)) {
        session.document = {
          ...session.document,
          revision: saved.revision,
          confirmed: saved.confirmed,
          topic: saved.topic,
          projectId: saved.projectId,
        };
        session.dirty = true;
      } else {
        session.document = {
          ...saved,
          attachments: appendAttachments(saved.attachments, session.document.attachments),
        };
        session.dirty = false;
      }
      const planned = changedValuePaths(before, session.document.settings);
      markEdited(session, planned);
      if (!ASSISTANT_PLAN_SOURCES[plan.source]) {
        forgetChanged(session, planned);
      }
      session.pending = null;
      session.notes = plan.notes;
      session.unsupported = plan.unsupported;
      clearError(session);
      emit();
      return;
    }

    const result = await api.applyPlan(session.document.id, plan.id, session.document.revision);
    if (sessions.get(session.document.id) !== session) {
      return;
    }
    pushUndo(session);
    const editedPaths = editedAfter(session, generation) ? editedSince(session, generation) : null;
    const applied = editedPaths === null
      ? ops
      : ops.filter((op) => !editConflicts(editedPaths, op.path));
    const before = session.document.settings;
    if (editedPaths !== null) {
      session.document = {
        ...result.document,
        settings: applySettingsOps(session.document.settings, applied),
        attachments: appendAttachments(result.document.attachments, session.document.attachments),
      };
      session.dirty = true;
    } else {
      session.document = {
        ...result.document,
        attachments: appendAttachments(result.document.attachments, session.document.attachments),
      };
      session.dirty = false;
    }
    const planned = changedValuePaths(before, session.document.settings);
    markEdited(session, planned);
    if (ASSISTANT_PLAN_SOURCES[plan.source]) {
      markChanged(session, changedOpPaths(before, session.document.settings, applied));
    } else {
      forgetChanged(session, planned);
    }
    session.pending = null;
    session.notes = result.plan.notes;
    session.unsupported = result.plan.unsupported;
    clearError(session);
    emit();
  } catch (error) {
    if (sessions.get(session.document.id) === session) {
      const key = sendError(error, ERROR_SAVE);
      if (key === ERROR_STALE && session.pending !== null) {
        session.pending = { ...session.pending, status: 'stale' };
      }
      setError(session, key);
      emit();
    }
    throw error;
  } finally {
    session.applyingPlanId = null;
    session.busy = Math.max(0, session.busy - 1);
    emit();
  }
}

export function rejectConceptPlan(): void {
  const session = activeSession();
  if (session === null || session.pending === null) {
    return;
  }
  const plan = session.pending;
  session.pending = null;
  emit();
  if (!plan.id.startsWith(LOCAL_PLAN_PREFIX) && plan.status === 'proposed') {
    void api.rejectPlan(session.document.id, plan.id).catch((error: unknown) => {
      if (sessions.get(session.document.id) === session) {
        setError(session, sendError(error, ERROR_SAVE));
        emit();
      }
    });
  }
}

export async function confirmConcept(): Promise<void> {
  const session = requireSession();
  if (session.document.confirmed) {
    if (!session.dirty) {
      return;
    }
    session.busy += 1;
    emit();
    try {
      await saveSelections(session);
    } catch (error) {
      setError(session, sendError(error, ERROR_SAVE));
      emit();
      throw error;
    } finally {
      session.busy = Math.max(0, session.busy - 1);
      emit();
    }
    return;
  }
  if (session.pending !== null) {
    setError(session, ERROR_PENDING);
    emit();
    throw new Error(ERROR_PENDING);
  }
  if (session.applyingPlanId !== null) {
    setError(session, ERROR_BUSY);
    emit();
    throw new Error(ERROR_BUSY);
  }
  const validation = validateConcept(session.document.settings, session.catalog);
  if (!validation.ok) {
    setError(session, ERROR_INVALID);
    session.unsupported = validation.blocked.map((entry) => localizedIssue(session, entry.key));
    emit();
    throw new Error(ERROR_INVALID);
  }

  const generation = session.editGeneration;
  session.busy += 1;
  emit();
  try {
    await saveSelections(session);
    const confirmed = await api.confirm(session.document.id, session.document.revision);
    if (sessions.get(session.document.id) !== session) {
      return;
    }
    if (editedAfter(session, generation)) {
      session.document = {
        ...session.document,
        confirmed: true,
        revision: confirmed.revision,
      };
      session.dirty = true;
    } else {
      session.document = {
        ...confirmed,
        attachments: appendAttachments(confirmed.attachments, session.document.attachments),
      };
      session.dirty = false;
    }
    session.undo = [];
    session.pending = null;
    clearError(session);
    emit();
  } catch (error) {
    if (sessions.get(session.document.id) === session) {
      setError(session, sendError(error, ERROR_SAVE));
      emit();
    }
    throw error;
  } finally {
    session.busy = Math.max(0, session.busy - 1);
    emit();
  }
}

export async function createConceptStyle(
  prompt: string,
  attachment?: Attachment,
): Promise<void> {
  const session = requireSession();
  if (session.document.confirmed) {
    setError(session, ERROR_LOCKED);
    emit();
    throw new Error(ERROR_LOCKED);
  }
  if (attachment !== undefined && attachment.kind !== 'reference' && attachment.kind !== 'link') {
    setError(session, ERROR_STYLE_ATTACHMENT);
    emit();
    throw new Error(ERROR_STYLE_ATTACHMENT);
  }
  if (prompt.trim() === '' && attachment === undefined) {
    setError(session, ERROR_EMPTY);
    emit();
    throw new Error(ERROR_EMPTY);
  }
  const generation = session.editGeneration;
  session.busy += 1;
  emit();
  try {
    if (session.dirty) await saveSelections(session);
    const job = await api.submitStyle(session.document.id, prompt, attachment);
    await runJob(session, job, generation, attachment === undefined ? [] : [attachment]);
  } catch (error) {
    if (sessions.get(session.document.id) === session) {
      setError(session, sendError(error, ERROR_JOB));
      emit();
    }
    throw error;
  } finally {
    session.busy = Math.max(0, session.busy - 1);
    emit();
  }
}

export async function analyzeConceptReference(attachment: Attachment): Promise<void> {
  const session = requireSession();
  if (attachment.kind !== 'reference' && attachment.kind !== 'link') {
    setError(session, ERROR_INVALID);
    emit();
    throw new Error(ERROR_INVALID);
  }
  if (session.document.confirmed) {
    setError(session, ERROR_LOCKED);
    emit();
    throw new Error(ERROR_LOCKED);
  }
  const generation = session.editGeneration;
  session.busy += 1;
  emit();
  try {
    if (session.dirty) await saveSelections(session);
    const job = await api.submitReference(session.document.id, attachment);
    await runJob(session, job, generation, [attachment]);
  } catch (error) {
    if (sessions.get(session.document.id) === session) {
      setError(session, sendError(error, ERROR_JOB));
      emit();
    }
    throw error;
  } finally {
    session.busy = Math.max(0, session.busy - 1);
    emit();
  }
}

export async function reloadConceptCatalog(): Promise<void> {
  const session = activeSession();
  if (session === null) {
    return;
  }
  await loadCatalog(session);
}

export function resetConceptSessions(): void {
  epoch += 1;
  startToken += 1;
  sessions = new Map();
  activeId = null;
  emit();
}

/** Whether the screen runs on the mock boundary, which answers from synthetic data. */
export function conceptApiIsMock(): boolean {
  return api instanceof MockConceptApi;
}

export function configureConceptApi(next: ConceptApi): void {
  api = next;
  epoch += 1;
  startToken += 1;
  sessions = new Map();
  activeId = null;
  emit();
}

export async function loadConceptDeployment(
  signal?: AbortSignal,
): Promise<'local' | 'hosted'> {
  if (signal?.aborted) {
    throw new DOMException('Aborted', 'AbortError');
  }
  const deployment = await api.deployment();
  if (signal?.aborted) {
    throw new DOMException('Aborted', 'AbortError');
  }
  return deployment;
}

async function loadCatalog(session: SessionState): Promise<void> {
  const request = session.catalogRequest + 1;
  session.catalogRequest = request;
  session.loading = true;
  emit();
  try {
    const catalog = await api.catalog();
    if (session.catalogRequest !== request || sessions.get(session.document.id) !== session) {
      return;
    }
    session.catalog = catalog;
    session.loading = false;
    setError(session, null);
    emit();
  } catch (error) {
    if (session.catalogRequest !== request || sessions.get(session.document.id) !== session) {
      return;
    }
    session.loading = false;
    setError(session, ERROR_CATALOG);
    emit();
    throw error;
  }
}

async function saveSelections(session: SessionState): Promise<void> {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const generation = session.editGeneration;
    const saved = await api.save(session.document.id, cloneSettings(session.document.settings));
    if (sessions.get(session.document.id) !== session) {
      return;
    }
    if (!editedAfter(session, generation)) {
      session.document = {
        ...saved,
        attachments: appendAttachments(saved.attachments, session.document.attachments),
      };
      session.dirty = false;
      return;
    }
    session.document = {
      ...session.document,
      revision: saved.revision,
      confirmed: saved.confirmed,
      topic: saved.topic,
      projectId: saved.projectId,
    };
    session.dirty = true;
  }
  const error = new ConceptApiError('revision_conflict', 409, ERROR_BUSY);
  setError(session, ERROR_BUSY);
  emit();
  throw error;
}

async function runJob(
  session: SessionState,
  initialJob: ConceptJob,
  generation: number,
  attachments: readonly Attachment[] = [],
): Promise<ConceptJob> {
  let job = initialJob;
  addJob(session, job);
  emit();
  let polls = 0;
  while (job.state === 'queued' || job.state === 'running') {
    polls += 1;
    if (polls > MAX_POLLS) {
      setError(session, ERROR_JOB);
      emit();
      throw new Error(ERROR_JOB);
    }
    if (sessions.get(session.document.id) !== session) {
      return job;
    }
    job = await api.getJob(job.id);
    if (sessions.get(session.document.id) !== session) {
      return job;
    }
    updateJob(session, job);
    emit();
  }
  if (job.state !== 'succeeded') {
    setError(session, ERROR_JOB);
    emit();
    throw new Error(ERROR_JOB);
  }
  if (job.kind === 'style') {
    try {
      await loadCatalog(session);
    } catch {
      // The pending plan stays visible; applying it reports the missing style.
    }
  }
  applyJobResult(session, job, generation, attachments);
  return job;
}

function addJob(session: SessionState, job: ConceptJob): void {
  const index = session.jobs.findIndex((entry) => entry.id === job.id);
  if (index === -1) {
    session.jobs = [...session.jobs, job].slice(-8);
  } else {
    const next = [...session.jobs];
    next[index] = job;
    session.jobs = next;
  }
}

function updateJob(session: SessionState, job: ConceptJob): void {
  addJob(session, job);
}

function applyJobResult(
  session: SessionState,
  job: ConceptJob,
  generation: number,
  attachments: readonly Attachment[],
): void {
  const result = job.result;
  if (result === undefined) {
    setError(session, ERROR_JOB);
    emit();
    return;
  }
  if (result.revision !== undefined) {
    session.document = { ...session.document, revision: result.revision };
  }
  if (result.attachments !== undefined) {
    session.document = {
      ...session.document,
      attachments: [
        ...result.attachments,
        ...appendAttachments(
          session.document.attachments.filter((attachment) => attachment.kind !== 'text'),
          attachments.filter((attachment) => attachment.kind !== 'text'),
        ),
      ],
    };
  } else if (attachments.length > 0) {
    session.document = {
      ...session.document,
      attachments: appendAttachments(session.document.attachments, attachments),
    };
  }
  session.notes = result.notes;
  session.unsupported = result.unsupported;
  const plan = result.plan;
  if (plan === null) {
    clearError(session);
    emit();
    return;
  }
  const ops = setPlanOps(plan);
  if (session.document.confirmed && planTouchesLockedFields(ops)) {
    setError(session, ERROR_LOCKED);
    emit();
    return;
  }
  const edited = editedSince(session, generation);
  const safeOps = ops.filter((op) => !editConflicts(edited, op.path));
  const candidate = applySettingsOps(session.document.settings, safeOps);
  const validation = validateConcept(candidate, session.catalog);
  if (!validation.ok) {
    setError(session, ERROR_INVALID);
    session.unsupported = [
      ...result.unsupported,
      ...validation.blocked.map((entry) => localizedIssue(session, entry.key)),
    ];
    session.pending = null;
    emit();
    return;
  }

  if (plan.status === 'applied' || plan.requires_confirmation === false) {
    if (safeOps.length > 0) {
      pushUndo(session);
      const before = session.document.settings;
      session.document = {
        ...session.document,
        settings: candidate,
        revision: plan.applied_revision ?? session.document.revision + 1,
      };
      const planned = changedValuePaths(before, candidate);
      markEdited(session, planned);
      if (ASSISTANT_PLAN_SOURCES[plan.source]) {
        markChanged(session, changedOpPaths(before, candidate, safeOps));
      } else {
        forgetChanged(session, planned);
      }
    }
    session.pending = null;
    session.dirty = safeOps.length !== ops.length;
    clearError(session);
    emit();
    return;
  }

  if (safeOps.length === 0) {
    session.pending = null;
    setError(session, ERROR_INVALID);
    emit();
    return;
  }
  session.pending = {
    ...plan,
    ops: safeOps,
    status: 'proposed',
    requires_confirmation: true,
  };
  clearError(session);
  emit();
}

function textMaterialCount(
  existing: readonly Attachment[],
  incoming: readonly Attachment[],
): number {
  const ids = new Set(existing.filter((attachment) => attachment.kind === 'text').map((attachment) => attachment.id));
  for (const attachment of incoming) {
    if (attachment.kind === 'text') {
      ids.add(attachment.id);
    }
  }
  return ids.size;
}

async function hydrateTextAttachments(attachments: readonly Attachment[]): Promise<Attachment[]> {
  const hydrated: Attachment[] = [];
  for (const attachment of attachments) {
    if (attachment.kind === 'text' && attachment.text === undefined && attachment.file !== undefined) {
      hydrated.push({ ...attachment, text: await readTextFile(attachment.file) });
    } else {
      hydrated.push(attachment);
    }
  }
  return hydrated;
}

function appendAttachments(
  existing: readonly Attachment[],
  incoming: readonly Attachment[],
): Attachment[] {
  const seen = new Set(existing.map((attachment) => attachment.id));
  const next = [...existing];
  for (const attachment of incoming) {
    if (!seen.has(attachment.id)) {
      seen.add(attachment.id);
      next.push(attachment);
    }
  }
  return next;
}
