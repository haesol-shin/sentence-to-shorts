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
  UndoEntry,
} from './types';

interface SessionState {
  document: ScriptDocument;
  confirm: ScriptApi['confirm'];
  confirmedDocument: ScriptDocument | null;
  serverBacked: boolean;
  busy: boolean;
  error: string | null;
  targetSceneId: string | null;
  workingSceneId: string | null;
  rewrite: RewriteProposal | null;
  tone: ToneProposal | null;
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
  serverBacked: boolean,
): SessionState {
  return {
    document,
    confirm,
    confirmedDocument: null,
    serverBacked,
    busy: false,
    error: null,
    targetSceneId: null,
    workingSceneId: null,
    rewrite: null,
    tone: null,
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
  return jobRunning(state) || state.rewrite !== null || state.tone !== null;
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
    changedSceneIds: state.changedSceneIds,
    highlightedSceneId: state.highlightedSceneId,
    focusToken: state.focusToken,
    totalSeconds: totalSeconds(state.document),
    canUndo: state.undo !== null && !jobRunning(state) && state.rewrite === null,
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

function markUndo(state: SessionState): void {
  state.undo = {
    document: cloneDocument(state.document),
    changedSceneIds: [...state.changedSceneIds],
  };
}

function clearUndo(state: SessionState): void {
  state.undo = null;
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
      }))
    : openServerScript(serverVideoId, target);
  opening = opened
    .then(({ document, confirm }) => {
      if (token !== openToken) {
        return;
      }
      session = createSession(document, confirm, serverVideoId !== null);
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

export function setLength(duration: TargetDuration): void {
  const state = requireSession();
  if (state === null || structureLocked(state)) {
    return;
  }
  state.document = withDuration(state.document, duration);
  const count = getScriptSceneCounts()[DURATIONS.indexOf(duration)];
  if (count !== undefined) {
    applySceneCount(state, count);
  }
  clearUndo(state);
  emit();
}

export function setSceneCount(count: number): void {
  const state = requireSession();
  if (state === null || !getScriptSceneCounts().includes(count) || structureLocked(state)) {
    return;
  }
  applySceneCount(state, count);
  clearUndo(state);
  emit();
}

export function setRegister(register: Register): void {
  const state = requireSession();
  if (state === null || jobRunning(state) || state.rewrite !== null) {
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
  state.document = withLineText(state.document, sceneId, lineId, text);
  clearUndo(state);
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
  state.document = next;
  state.lineIdMax = Math.max(
    state.lineIdMax,
    maxEntityNumber(
      Object.values(next.scenes).flatMap((entry) => entry.lines.map((line) => line.id)),
      'l',
    ),
  );
  state.error = null;
  clearUndo(state);
  emit();
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
  state.document = withSceneOrder(state.document, order);
  clearUndo(state);
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
  state.document = withSceneOrder(state.document, order);
  clearUndo(state);
  emit();
}

export async function rewriteScene(sceneId: string): Promise<void> {
  const state = requireSession();
  if (
    state === null ||
    jobRunning(state) ||
    state.tone !== null ||
    state.rewrite !== null ||
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
  emit();
  try {
    const after = await api.rewrite(state.document, sceneId, {
      signal: controller.signal,
    });
    if (token !== rewriteToken) {
      return;
    }
    const scene = state.document.scenes[sceneId];
    state.workingSceneId = null;
    rewriteController = null;
    if (scene === undefined) {
      emit();
      return;
    }
    state.rewrite = {
      sceneId,
      before: scene.lines.map((line) => line.display_text),
      after,
    };
    emit();
  } catch (error) {
    if (token !== rewriteToken) {
      return;
    }
    state.workingSceneId = null;
    rewriteController = null;
    if (!(error instanceof ScriptApiError && error.code === 'cancelled')) {
      state.error = 'script.error.rewrite';
    }
    emit();
  }
}

export function stopRewrite(): void {
  const state = requireSession();
  if (state === null || state.workingSceneId === null) {
    return;
  }
  rewriteToken += 1;
  rewriteController?.abort();
  rewriteController = null;
  state.workingSceneId = null;
  emit();
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
    target.lines = target.lines.map((line, index) => {
      const text = proposal.after[index] ?? line.display_text;
      return { ...line, display_text: text, speech_text: text };
    });
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
  if (state === null || state.undo === null || jobRunning(state) || state.rewrite !== null) {
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
