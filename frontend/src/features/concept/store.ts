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
  changeCardTune,
  changeConceptValue,
  cloneSettings,
  isConceptLockedPath,
  isStyleInstruction,
  normalizePointer,
  planImpact,
  planTouchesLockedFields,
  resetConceptValue,
  validateConcept,
  type ChangeResult,
} from './model';
import {
  ConceptApiError,
  createMockConceptApi,
  MockConceptApi,
  type ConceptApi,
  type ConceptStartInput,
} from './api';
import type {
  Attachment,
  CardTune,
  ConceptCatalog,
  ConceptDocument,
  ConceptJob,
  ConceptSnapshot,
  LockKey,
  Plan,
  Settings,
  SetOp,
} from './types';

const ERROR_INVALID = 'concept.error.invalidCombination';
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

function pushUndo(session: SessionState): void {
  session.undo = [cloneSettings(session.document.settings)];
}

function sameSettings(left: Settings, right: Settings): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
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
  paths: readonly string[],
): void {
  if (result.kind === 'invalid') {
    setError(session, ERROR_INVALID);
    emit();
    return;
  }
  if (result.kind === 'replacement') {
    openReplacementPlan(session, result.ops);
    return;
  }
  if (sameSettings(result.settings, session.document.settings)) {
    clearError(session);
    emit();
    return;
  }
  pushUndo(session);
  session.document = { ...session.document, settings: result.settings };
  session.dirty = true;
  markEdited(session, result.editedPaths.length > 0 ? result.editedPaths : paths);
  clearError(session);
  emit();
}

export async function beginConcept(input: ConceptStartInput): Promise<ConceptDocument | null> {
  const token = ++startToken;
  const currentEpoch = epoch;
  const created = await api.create(input);
  if (currentEpoch !== epoch) {
    return null;
  }
  const session = createSession(created);
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
 * edited since are kept, and the rest follow the server too.
 */
export async function reloadConcept(videoId: string): Promise<void> {
  const session = sessions.get(videoId);
  if (session === undefined) {
    return;
  }
  const generation = session.editGeneration;
  const loaded = await api.load(videoId);
  if (sessions.get(videoId) !== session) {
    return;
  }
  const keep = session.dirty || editedAfter(session, generation);
  session.document = {
    ...loaded,
    settings: keep ? session.document.settings : loaded.settings,
    attachments: appendAttachments(loaded.attachments, session.document.attachments.filter((entry) => entry.kind !== 'text')),
  };
  emit();
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

export function chooseConcept(path: string, value: unknown): void {
  const session = activeSession();
  if (session === null) {
    return;
  }
  const pointer = normalizePointer(path);
  if (pointer !== null && session.document.confirmed && isConceptLockedPath(pointer)) {
    setError(session, ERROR_LOCKED);
    emit();
    return;
  }
  const result = changeConceptValue(session.document.settings, path, value, session.catalog);
  commitChange(session, result, pointer === null ? [] : [pointer]);
}

/**
 * Select a story card with the four values shown in its fine-tune panel.
 * The values of the card being left stay with the video session, so a step
 * change does not reset them, and the card being entered gets its own values.
 */
export function chooseCardTune(id: string): void {
  const session = activeSession();
  if (session === null) {
    return;
  }
  if (session.document.confirmed) {
    setError(session, ERROR_LOCKED);
    emit();
    return;
  }
  const settings = session.document.settings;
  const active = cardIdForSettings(settings);
  if (active === id) {
    return;
  }
  const tune = session.cardTunes[id] ?? cardTunePreset(id, session.catalog);
  if (tune === null) {
    setError(session, ERROR_INVALID);
    emit();
    return;
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
  commitChange(session, result, ['/format/card_id', '/format/story_structure']);
}

export function resetConcept(path: string): void {
  const session = activeSession();
  if (session === null) {
    return;
  }
  const pointer = normalizePointer(path);
  if (pointer !== null && session.document.confirmed && isConceptLockedPath(pointer)) {
    setError(session, ERROR_LOCKED);
    emit();
    return;
  }
  const result = resetConceptValue(session.document.settings, path, session.catalog);
  commitChange(session, result, pointer === null ? [] : [pointer]);
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
  session.document = { ...session.document, settings };
  session.dirty = true;
  markEdited(session, ['*']);
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
    if (editedAfter(session, generation)) {
      const edited = editedSince(session, generation);
      const safeOps = ops.filter((op) => !edited.has(op.path) && !edited.has('*'));
      session.document = {
        ...result.document,
        settings: applySettingsOps(session.document.settings, safeOps),
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
  const safeOps = ops.filter((op) => !edited.has(op.path) && !edited.has('*'));
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
      session.document = {
        ...session.document,
        settings: candidate,
        revision: plan.applied_revision ?? session.document.revision + 1,
      };
      markEdited(session, safeOps.map((op) => op.path));
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
