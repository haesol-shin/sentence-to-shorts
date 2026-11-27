import { useSyncExternalStore } from 'react';

import type { Language } from '@/shared/api/client';

import { createMockScriptApi, ScriptApiError, type ScriptApi } from './api';
import {
  buildToneProposal,
  cloneDocument,
  DURATIONS,
  firstTooLongLine,
  getScriptSceneCounts,
  hasDuplicateOrder,
  hasEmptyLine,
  isConfirmed,
  MAX_SCENE_LINES,
  maxEntityNumber,
  totalSeconds,
  withAddedLine,
  withDuration,
  withLineText,
  withSceneCount,
  withSceneOrder,
} from './model';
import { openServerScript } from './server-script';
import type {
  Register,
  RewriteProposal,
  ScriptDocument,
  ScriptSnapshot,
  ScriptTarget,
  TargetDuration,
  ToneProposal,
  ScriptLine,
  UndoEntry,
} from './types';

interface SessionState {
  document: ScriptDocument;
  confirm: ScriptApi['confirm'];
  requestRewrite: ScriptApi['rewrite'];
  sync: ScriptApi['sync'] | null;
  conceptRevision: number | null;
  rebuild: ((document: ScriptDocument, settings: NonNullable<ScriptSnapshot['settings']>) => Promise<ScriptDocument>) | null;
  confirmedDocument: ScriptDocument | null;
  serverBacked: boolean;
  busy: boolean;
  error: string | null;
  targetSceneId: string | null;
  workingSceneId: string | null;
  rewrite: RewriteProposal | null;
  tone: ToneProposal | null;
  settings: ScriptSnapshot['settings'];
  unsupported: string[];
  changedSceneIds: string[];
  highlightedSceneId: string | null;
  focusToken: number;
  undo: UndoEntry | null;
  sceneIdMax: number;
  lineIdMax: number;
}

const EMPTY_TARGET: ScriptTarget = { id: null, topic: null, script: null };

let api: ScriptApi = createMockScriptApi();
let session: SessionState | null = null;
let targetKey: string | null = null;
let opening: Promise<void> | null = null;
let openToken = 0;
let loadError: string | null = null;
let rewriteToken = 0;
let rewriteController: AbortController | null = null;

const listeners = new Set<() => void>();
let cached: ScriptSnapshot | null = null;
let cacheDirty = true;

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

function createSession(
  document: ScriptDocument,
  confirm: ScriptApi['confirm'],
  requestRewrite: ScriptApi['rewrite'],
  rebuild: SessionState['rebuild'],
  sync: SessionState['sync'],
  serverBacked: boolean,
): SessionState {
  return {
    document,
    confirm,
    requestRewrite,
    rebuild,
    sync,
    conceptRevision: null,
    confirmedDocument: null,
    serverBacked,
    busy: false,
    error: null,
    targetSceneId: null,
    workingSceneId: null,
    rewrite: null,
    tone: null,
    settings: null,
    unsupported: [],
    changedSceneIds: [],
    highlightedSceneId: null,
    focusToken: 0,
    undo: null,
    sceneIdMax: maxEntityNumber(Object.keys(document.scenes), 's'),
    lineIdMax: maxEntityNumber(
      Object.values(document.scenes).flatMap((scene) => scene.lines.map((line) => line.id)),
      'l',
    ),
  };
}

function jobRunning(state: SessionState): boolean {
  return state.busy || state.workingSceneId !== null;
}

function structureLocked(state: SessionState): boolean {
  return jobRunning(state) || state.rewrite !== null || state.tone !== null || state.settings !== null;
}

function blockedReason(state: SessionState): string | null {
  if (jobRunning(state)) {
    return 'script.reason.working';
  }
  if (state.rewrite !== null) {
    return 'script.reason.rewrite';
  }
  if (state.tone !== null) {
    return 'script.reason.tone';
  }
  if (state.settings !== null) return 'script.reason.settings';
  if (hasDuplicateOrder(state.document)) {
    return 'script.reason.duplicateOrder';
  }
  if (hasEmptyLine(state.document)) {
    return 'script.reason.empty';
  }
  if (firstTooLongLine(state.document) !== null) {
    return 'script.reason.lineTooLong';
  }
  return null;
}

function buildSnapshot(): ScriptSnapshot | null {
  if (session === null) {
    return null;
  }
  const state = session;
  return {
    document: state.document,
    busy: jobRunning(state),
    error: state.error,
    targetSceneId: state.targetSceneId,
    workingSceneId: state.workingSceneId,
    rewrite: state.rewrite,
    tone: state.tone,
    settings: state.settings,
    unsupported: state.unsupported,
    changedSceneIds: state.changedSceneIds,
    highlightedSceneId: state.highlightedSceneId,
    focusToken: state.focusToken,
    totalSeconds: totalSeconds(state.document),
    canUndo: state.undo !== null && !jobRunning(state) && state.rewrite === null && state.settings === null,
    confirmed: state.serverBacked ? state.confirmedDocument === state.document : isConfirmed(state.document),
    nextBlockedReason: blockedReason(state),
  };
}

function readSnapshot(): ScriptSnapshot | null {
  if (cacheDirty) {
    cached = buildSnapshot();
    cacheDirty = false;
  }
  return cached;
}

export function getScriptSnapshot(): ScriptSnapshot | null {
  return readSnapshot();
}

export function useScript(): ScriptSnapshot | null {
  return useSyncExternalStore(subscribe, readSnapshot, readSnapshot);
}

/** True when the script session could not be opened. */
export function useScriptLoadFailed(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => loadError !== null,
    () => false,
  );
}

function requireSession(): SessionState | null {
  if (session === null) {
    return null;
  }
  return session;
}

/**
 * Keep the script before a change, for one undo. Typing on in the same line
 * keeps the entry from its first key, so undo takes back the whole edit.
 */
function markUndo(state: SessionState, line: string | null = null): void {
  if (line !== null && state.undo?.line === line) {
    return;
  }
  state.undo = {
    document: cloneDocument(state.document),
    changedSceneIds: [...state.changedSceneIds],
    line,
  };
}

function markChanged(state: SessionState, sceneId: string): void {
  if (!state.changedSceneIds.includes(sceneId)) {
    state.changedSceneIds = [...state.changedSceneIds, sceneId];
  }
}

function dropMissingTargets(state: SessionState): void {
  const exists = (id: string) => state.document.scenes[id] !== undefined;
  if (state.targetSceneId !== null && !exists(state.targetSceneId)) {
    state.targetSceneId = null;
  }
  if (state.highlightedSceneId !== null && !exists(state.highlightedSceneId)) {
    state.highlightedSceneId = null;
  }
}

/**
 * Keep the head of the order and append empty scenes at the tail. The floors
 * remember the ids this session has issued, so a dropped scene's id is never
 * handed to a new scene, and a dropped scene loses its changed mark.
 */
function applySceneCount(state: SessionState, count: number): void {
  const next = withSceneCount(state.document, count, state.sceneIdMax, state.lineIdMax);
  state.sceneIdMax = Math.max(
    state.sceneIdMax,
    maxEntityNumber(Object.keys(next.scenes), 's'),
  );
  state.lineIdMax = Math.max(
    state.lineIdMax,
    maxEntityNumber(
      Object.values(next.scenes).flatMap((scene) => scene.lines.map((line) => line.id)),
      'l',
    ),
  );
  state.document = next;
  state.changedSceneIds = state.changedSceneIds.filter((id) => next.scenes[id] !== undefined);
  dropMissingTargets(state);
}

/**
 * Open the script once per creation attempt. The server video id is separate,
 * and changing the interface language or the topic does not reopen the session.
 */
export function ensureScript(
  language: Language,
  target: ScriptTarget = EMPTY_TARGET,
  serverVideoId: string | null = null,
): Promise<void> {
  const key = target.id ?? '';
  if (session !== null && targetKey === key) {
    return Promise.resolve();
  }
  if (opening !== null && targetKey === key) {
    return opening;
  }

  openToken += 1;
  rewriteToken += 1;
  rewriteController?.abort();
  rewriteController = null;
  session = null;
  opening = null;
  loadError = null;
  targetKey = key;
  emit();

  const token = ++openToken;
  const currentApi = api;
  const opened = serverVideoId === null
    ? currentApi.open(language, target).then((document) => ({
        document,
        confirm: currentApi.confirm.bind(currentApi),
        rewrite: currentApi.rewrite.bind(currentApi),
        rebuild: null,
        sync: null,
      }))
    : openServerScript(serverVideoId, target);
  opening = opened
    .then(({ document, confirm, rewrite, rebuild, sync }) => {
      if (token !== openToken) {
        return;
      }
      session = createSession(document, confirm, rewrite, rebuild, sync ?? null, serverVideoId !== null);
      opening = null;
      emit();
    })
    .catch(() => {
      if (token !== openToken) {
        return;
      }
      opening = null;
      loadError = 'script.error.load';
      emit();
    });
  return opening;
}

export function proposeScriptSettings({ duration, count }: Partial<NonNullable<ScriptSnapshot['settings']>>): void {
  const state = requireSession();
  if (state === null || structureLocked(state)) return;
  const nextDuration = duration ?? state.document.target_duration_s;
  const nextCount = count ?? (duration === undefined ? undefined : getScriptSceneCounts()[DURATIONS.indexOf(duration)])
    ?? state.document.scene_order.length;
  if (nextDuration === state.document.target_duration_s && nextCount === state.document.scene_order.length) return;
  state.settings = { duration: nextDuration, count: nextCount };
  state.error = null;
  emit();
}

export function discardScriptSettings(): void {
  const state = requireSession();
  if (state === null || state.settings === null) return;
  state.settings = null;
  emit();
}

export async function applyScriptSettings(): Promise<void> {
  const state = requireSession();
  if (state === null || state.settings === null || jobRunning(state)) return;
  const settings = state.settings;
  state.settings = null;
  if (state.rebuild === null) {
    if (settings.duration !== state.document.target_duration_s) setLength(settings.duration);
    else setSceneCount(settings.count);
    return;
  }
  state.busy = true;
  state.error = null;
  emit();
  try {
    const rebuilt = await state.rebuild(state.document, settings);
    markUndo(state);
    state.document = rebuilt;
    state.changedSceneIds = [...rebuilt.scene_order];
    dropMissingTargets(state);
  } catch {
    state.error = 'script.error.rewrite';
    state.settings = settings;
  } finally {
    state.busy = false;
    emit();
  }
}

export function setLength(duration: TargetDuration): void {
  const state = requireSession();
  if (state === null || structureLocked(state)) {
    return;
  }
  markUndo(state);
  state.document = withDuration(state.document, duration);
  const count = getScriptSceneCounts()[DURATIONS.indexOf(duration)];
  if (count !== undefined) {
    applySceneCount(state, count);
  }
  emit();
}

export function setSceneCount(count: number): void {
  const state = requireSession();
  if (state === null || !getScriptSceneCounts().includes(count) || structureLocked(state)) {
    return;
  }
  markUndo(state);
  applySceneCount(state, count);
  emit();
}

export function setRegister(register: Register): void {
  const state = requireSession();
  if (state === null || jobRunning(state) || state.rewrite !== null || state.settings !== null) {
    return;
  }
  state.error = null;
  const from = state.tone?.from ?? state.document.register;
  if (register === from) {
    if (state.tone !== null) {
      state.tone = null;
      emit();
    }
    return;
  }
  const source = { ...state.document, register: from };
  const proposal = buildToneProposal(source, register);
  if (proposal.scenes.length === 0) {
    state.tone = null;
    state.error = 'script.tone.none';
    emit();
    return;
  }
  state.tone = proposal;
  emit();
}

export function editLine(sceneId: string, lineId: string, text: string): void {
  const state = requireSession();
  if (state === null || state.busy || state.workingSceneId === sceneId) {
    return;
  }
  state.error = null;
  if (state.tone !== null) {
    state.tone = null;
  }
  if (state.rewrite?.sceneId === sceneId) {
    state.rewrite = null;
  }
  markUndo(state, lineId);
  state.document = withLineText(state.document, sceneId, lineId, text);
  emit();
}

/** Add one empty line to a scene, up to the same four-line cap as edit. */
export function addLine(sceneId: string): void {
  const state = requireSession();
  if (state === null || structureLocked(state)) {
    return;
  }
  const scene = state.document.scenes[sceneId];
  if (scene === undefined || scene.lines.length >= MAX_SCENE_LINES) {
    return;
  }
  const next = withAddedLine(state.document, sceneId, state.lineIdMax);
  if (next === state.document) {
    return;
  }
  markUndo(state);
  state.document = next;
  state.lineIdMax = Math.max(
    state.lineIdMax,
    maxEntityNumber(
      Object.values(next.scenes).flatMap((entry) => entry.lines.map((line) => line.id)),
      'l',
    ),
  );
  state.error = null;
  emit();
}

function replaceLines(state: SessionState, sceneId: string, lines: ScriptLine[]): void {
  markUndo(state);
  state.document = {
    ...state.document,
    scenes: {
      ...state.document.scenes,
      [sceneId]: { ...state.document.scenes[sceneId], lines },
    },
  };
  state.error = null;
  emit();
}

export function deleteLine(sceneId: string, lineId: string): void {
  const state = requireSession();
  if (state === null || structureLocked(state)) {
    return;
  }
  const scene = state.document.scenes[sceneId];
  if (scene === undefined || scene.lines.length <= 1) {
    return;
  }
  const lines = scene.lines.filter((line) => line.id !== lineId);
  if (lines.length !== scene.lines.length) {
    replaceLines(state, sceneId, lines);
  }
}

export function moveLineTo(sceneId: string, lineId: string, index: number): void {
  const state = requireSession();
  if (state === null || structureLocked(state)) {
    return;
  }
  const scene = state.document.scenes[sceneId];
  if (scene === undefined || index < 0 || index >= scene.lines.length) {
    return;
  }
  const from = scene.lines.findIndex((line) => line.id === lineId);
  if (from < 0 || from === index) {
    return;
  }
  const lines = [...scene.lines];
  lines.splice(from, 1);
  lines.splice(index, 0, scene.lines[from]);
  replaceLines(state, sceneId, lines);
}

export function moveScene(sceneId: string, delta: number): void {
  const state = requireSession();
  if (state === null || structureLocked(state)) {
    return;
  }
  const from = state.document.scene_order.indexOf(sceneId);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= state.document.scene_order.length) {
    return;
  }
  const order = [...state.document.scene_order];
  const [moved] = order.splice(from, 1);
  if (moved === undefined) {
    return;
  }
  order.splice(to, 0, moved);
  markUndo(state);
  state.document = withSceneOrder(state.document, order);
  emit();
}

export function moveSceneTo(sceneId: string, index: number): void {
  const state = requireSession();
  if (state === null || structureLocked(state)) {
    return;
  }
  const from = state.document.scene_order.indexOf(sceneId);
  if (from < 0 || index < 0 || index >= state.document.scene_order.length || index === from) {
    return;
  }
  const order = [...state.document.scene_order];
  const [moved] = order.splice(from, 1);
  if (moved === undefined) {
    return;
  }
  order.splice(index, 0, moved);
  markUndo(state);
  state.document = withSceneOrder(state.document, order);
  emit();
}

export async function rewriteScene(sceneId: string, instruction?: string): Promise<void> {
  const state = requireSession();
  if (
    state === null ||
    structureLocked(state) ||
    state.document.scenes[sceneId] === undefined
  ) {
    return;
  }
  const token = ++rewriteToken;
  const controller = new AbortController();
  rewriteController = controller;
  state.targetSceneId = sceneId;
  state.workingSceneId = sceneId;
  state.error = null;
  state.unsupported = [];
  emit();
  try {
    const result = await state.requestRewrite(state.document, sceneId, {
      signal: controller.signal, instruction,
    });
    if (token !== rewriteToken) {
      return;
    }
    const scene = state.document.scenes[sceneId];
    state.workingSceneId = null;
    rewriteController = null;
    state.unsupported = result.unsupported;
    if (scene !== undefined && result.lines !== null) {
      state.rewrite = {
        sceneId,
        before: scene.lines.map((line) => line.display_text),
        after: result.lines,
      };
    }
    emit();
  } catch (error) {
    if (token !== rewriteToken) {
      return;
    }
    state.workingSceneId = null;
    rewriteController = null;
    state.error = error instanceof ScriptApiError && error.code === 'cancelled'
      ? 'script.stopped' : 'script.error.rewrite';
    emit();
  }
}

export function stopRewrite(): void {
  const state = requireSession();
  if (state === null || state.workingSceneId === null) {
    return;
  }
  rewriteController?.abort();
}

export function dismissRewrite(): void {
  const state = requireSession();
  if (state === null) {
    return;
  }
  state.rewrite = null;
  emit();
}

export function applyRewrite(): void {
  const state = requireSession();
  const proposal = state?.rewrite ?? null;
  if (state === null || proposal === null) {
    return;
  }
  const scene = state.document.scenes[proposal.sceneId];
  if (scene === undefined) {
    state.rewrite = null;
    emit();
    return;
  }
  markUndo(state);
  const next = cloneDocument(state.document);
  const target = next.scenes[proposal.sceneId];
  if (target !== undefined) {
    target.lines = proposal.after;
  }
  state.document = next;
  markChanged(state, proposal.sceneId);
  state.rewrite = null;
  state.error = null;
  emit();
}

export function applyTone(): void {
  const state = requireSession();
  const proposal = state?.tone ?? null;
  if (state === null || proposal === null) {
    return;
  }
  markUndo(state);
  const next = cloneDocument(state.document);
  next.register = proposal.to;
  for (const review of proposal.scenes) {
    const scene = next.scenes[review.sceneId];
    if (scene === undefined) {
      continue;
    }
    for (const line of review.lines) {
      const target = scene.lines.find((entry) => entry.id === line.lineId);
      if (target !== undefined) {
        target.display_text = line.after;
        target.speech_text = line.after;
      }
    }
    markChanged(state, review.sceneId);
  }
  state.document = next;
  state.tone = null;
  emit();
}

/**
 * Applies the tone change in one scene and leaves the other scenes' proposals
 * open, because the canon lets a user decide scene by scene or all at once.
 */
export function applyToneScene(sceneId: string): void {
  const state = requireSession();
  const proposal = state?.tone ?? null;
  if (state === null || proposal === null) {
    return;
  }
  const review = proposal.scenes.find((entry) => entry.sceneId === sceneId);
  if (review === undefined) {
    return;
  }
  const rest = proposal.scenes.filter((entry) => entry.sceneId !== sceneId);
  const next = cloneDocument(state.document);
  const scene = next.scenes[sceneId];
  if (scene === undefined) {
    state.tone = rest.length === 0 ? null : { ...proposal, scenes: rest };
    emit();
    return;
  }
  markUndo(state);
  for (const line of review.lines) {
    const target = scene.lines.find((entry) => entry.id === line.lineId);
    if (target !== undefined) {
      target.display_text = line.after;
      target.speech_text = line.after;
    }
  }
  next.register = proposal.to;
  state.document = next;
  markChanged(state, sceneId);
  state.tone = rest.length === 0 ? null : { ...proposal, scenes: rest };
  state.error = null;
  emit();
}

/** Drops the tone proposal for one scene and keeps the proposal open for the others. */
export function dismissToneScene(sceneId: string): void {
  const state = requireSession();
  const proposal = state?.tone ?? null;
  if (state === null || proposal === null) {
    return;
  }
  const rest = proposal.scenes.filter((entry) => entry.sceneId !== sceneId);
  if (rest.length === proposal.scenes.length) {
    return;
  }
  state.tone = rest.length === 0 ? null : { ...proposal, scenes: rest };
  state.error = null;
  emit();
}

export function dismissTone(): void {
  const state = requireSession();
  if (state === null || state.tone === null) {
    return;
  }
  state.tone = null;
  emit();
}

/** A changed-scene jump from the conversation: scroll there and tint its card grey. */
export function focusScene(sceneId: string): void {
  const state = requireSession();
  if (state === null || state.document.scenes[sceneId] === undefined) {
    return;
  }
  state.highlightedSceneId = sceneId;
  state.focusToken += 1;
  emit();
}

/**
 * Pull settings the conversation changed on the server into the open script.
 * The caller passes the concept session revision; a change in it, however it
 * came about, is what triggers the read. A locked script retries on the next call.
 */
export async function syncScriptSettings(conceptRevision: number): Promise<void> {
  const state = requireSession();
  if (state === null || state.sync == null) return;
  if (state.conceptRevision === null) {
    state.conceptRevision = conceptRevision;
    return;
  }
  if (state.conceptRevision === conceptRevision || structureLocked(state)) return;
  try {
    const next = await state.sync(state.document);
    if (session === state) {
      state.document = next;
      state.conceptRevision = conceptRevision;
      emit();
    }
  } catch {
    // The next save reports a real conflict.
  }
}

export function targetScene(sceneId: string): void {
  const state = requireSession();
  if (state === null || state.document.scenes[sceneId] === undefined) return;
  state.targetSceneId = sceneId;
  emit();
}

export function clearTarget(): void {
  const state = requireSession();
  if (state === null) {
    return;
  }
  state.targetSceneId = null;
  emit();
}

export function undo(): void {
  const state = requireSession();
  if (state === null || state.undo === null || jobRunning(state) || state.rewrite !== null || state.settings !== null) {
    return;
  }
  state.tone = null;
  state.document = state.undo.document;
  state.changedSceneIds = state.undo.changedSceneIds;
  state.undo = null;
  emit();
}

export async function confirmScript(): Promise<boolean> {
  const state = requireSession();
  if (state === null || blockedReason(state) !== null || state.busy) {
    return false;
  }
  state.busy = true;
  state.error = null;
  emit();
  try {
    const confirmed = await state.confirm(state.document);
    if (session !== state) {
      return false;
    }
    state.document = confirmed;
    state.confirmedDocument = confirmed;
    state.undo = null;
    return true;
  } catch {
    state.error = 'script.error.confirm';
    return false;
  } finally {
    state.busy = false;
    if (session === state) {
      emit();
    }
  }
}

/** Tests and the first screen use this to start from a clean mock session. */
export function resetScriptSessions(): void {
  openToken += 1;
  rewriteToken += 1;
  rewriteController?.abort();
  rewriteController = null;
  session = null;
  opening = null;
  targetKey = null;
  loadError = null;
  emit();
}

export function configureScriptApi(next: ScriptApi): void {
  api = next;
  resetScriptSessions();
}
