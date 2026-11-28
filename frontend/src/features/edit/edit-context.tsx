import {
  createContext,
  useContext,
  useEffect,
  useCallback,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from 'react';

import { ApiProblemError, retryJob } from '@/shared/api/client';

import type {
  BgmChoice,
  CaptionLayout,
  CaptionLayoutQuery,
  CaptionMode,
  CatalogItem,
  ChangePlan,
  EditApi,
  ErrorItem,
  Job,
  Mood,
  StyleOptions,
} from './api';
import { createEditApi, EditApiError, sceneFieldOps } from './api';
import {
  changedFields,
  duplicateScene,
  MAX_LINES_PER_SCENE,
  moveScene,
  newLocalId,
  scenesOf,
  totalEstimatedSeconds,
  stillIsReady,
  type BandField,
  type Line,
  type SceneFieldPatch,
  type Scene,
  type Video,
  type VideoView,
} from './model';
import { BGM_PATH, VOICE_PATH } from './sound/model';
import { EMPTY_BGM_WORK, useBgmWork, type BgmWork } from './sound/use-bgm-work';

export type EditPhase = 'idle' | 'stills' | 'video' | 'done';
export type { SceneFieldPatch } from './model';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  kind?:
    | 'noChange'
    | 'proposed'
    | 'applied'
    | 'error'
    | 'unsupported'
    | 'cancelled'
    | 'queueDiscarded'
    | 'stale'
    | 'videoStopped';
  targetId?: string | null;
  sceneIds?: string[];
  detail?: string;
}

interface ChatRequest {
  text: string;
  target: string | null;
}

export interface SceneBand {
  sceneId: string;
  fields: readonly BandField[];
  token: number;
}

export interface PreviewState {
  job: Job | null;
  stills: Record<string, string>;
  loading: boolean;
  error: string | null;
}

interface ReorderReview {
  order: string[];
  revision: number;
}

type BgmStatus = 'loading' | 'ready' | 'failed';

interface EditState {
  view: VideoView | null;
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  targetId: string | null;
  tab: string;
  unseen: readonly string[];
  band: SceneBand | null;
  pending: ChangePlan | null;
  pendingSelect: string | null;
  reorder: ReorderReview | null;
  job: Job | null;
  entryPreview: boolean;
  jobReadFailed: boolean;
  confirmedForOutput: boolean;
  finishedGeneration: string | null;
  chatJob: Job | null;
  messages: readonly ChatMessage[];
  sending: boolean;
  busy: boolean;
  sfx: readonly CatalogItem[];
  voices: readonly CatalogItem[];
  fonts: readonly CatalogItem[];
  bgm: readonly BgmChoice[];
  bgmStatus: BgmStatus;
  captionModes: readonly CaptionMode[] | null;
  style: StyleOptions | null;
  preview: PreviewState;
  actionError: string | null;
  changeErrors: readonly ErrorItem[];
}

const INITIAL: EditState = {
  view: null,
  loading: false,
  error: null,
  selectedId: null,
  targetId: null,
  tab: 'scenes',
  unseen: [],
  band: null,
  pending: null,
  pendingSelect: null,
  reorder: null,
  job: null,
  entryPreview: false,
  jobReadFailed: false,
  confirmedForOutput: false,
  finishedGeneration: null,
  chatJob: null,
  messages: [],
  sending: false,
  busy: false,
  sfx: [],
  voices: [],
  fonts: [],
  bgm: [],
  bgmStatus: 'loading',
  captionModes: null,
  style: null,
  preview: { job: null, stills: {}, loading: false, error: null },
  actionError: null,
  changeErrors: [],
};

type EditAction =
  | { type: 'loading' }
  | { type: 'loaded'; view: VideoView; selected: string | null; pending: ChangePlan | null; job: Job | null; entryPreview: boolean }
  | { type: 'refresh'; view: VideoView; band?: boolean }
  | { type: 'load-failed'; error?: string }
  | { type: 'select'; id: string }
  | { type: 'target'; id: string | null }
  | { type: 'tab'; tab: string }
  | { type: 'unseen'; ids: readonly string[] }
  | { type: 'pending'; plan: ChangePlan; selectAfter: string | null }
  | { type: 'pending-cleared' }
  | { type: 'reorder-review'; review: ReorderReview | null }
  | { type: 'busy'; value: boolean }
  | { type: 'job'; job: Job | null }
  | { type: 'entry-preview-finished' }
  | { type: 'job-read-failed' }
  | { type: 'output-confirmed'; value: boolean }
  | { type: 'generation-finished'; id: string }
  | { type: 'chat-job'; job: Job | null }
  | { type: 'message'; message: ChatMessage }
  | { type: 'sending'; value: boolean }
  | {
      type: 'catalog';
      sfx: readonly CatalogItem[];
      voices: readonly CatalogItem[];
      fonts: readonly CatalogItem[];
      style: StyleOptions | null;
    }
  | { type: 'bgm'; status: BgmStatus; tracks?: readonly BgmChoice[] }
  | { type: 'caption-modes'; modes: readonly CaptionMode[] | null }
  | { type: 'action-error'; error: string | null }
  | { type: 'change-errors'; errors: readonly ErrorItem[] }
  | { type: 'preview'; planId: string; preview: Partial<PreviewState> };

function phaseOf(job: Job | null, view: VideoView | null, entryPreview: boolean, finished: string | null): EditPhase {
  if (job === null || view === null || entryPreview) return 'idle';
  if (job.state === 'queued' || job.state === 'running' || job.state === 'cancelling') {
    return job.kind === 'preview' ? 'stills' : 'video';
  }
  if (job.state === 'succeeded') {
    if (job.kind === 'preview') return 'stills';
    if (view.build.final.state === 'fresh') return 'done';
    return finished === job.id ? 'idle' : 'video';
  }
  return 'idle';
}

function sceneProgress(job: Job | null, stage: 'still' | 'clip', sceneCount: number) {
  if (job?.progress.stage === stage && job.progress.total > 0) {
    return { done: job.progress.done, total: job.progress.total };
  }
  if (job?.stages.some((record) => record.stage === stage && record.state === 'done')) {
    return { done: sceneCount, total: sceneCount };
  }
  return { done: 0, total: sceneCount };
}

function selectedFor(view: VideoView, storedScene: string | null): string | null {
  const order = view.video.scene_order;
  const stored =
    storedScene !== null && view.video.scenes[storedScene] !== undefined ? storedScene : null;
  return stored ?? order[0] ?? null;
}

function reducer(state: EditState, action: EditAction): EditState {
  switch (action.type) {
    case 'loading':
      return { ...INITIAL, loading: true };
    case 'loaded': {
      const { selected } = action;
      return {
        ...INITIAL,
        view: action.view,
        selectedId: selected,
        targetId: selected,
        job: action.job,
        entryPreview: action.entryPreview,
        pending: action.pending,
        pendingSelect: action.pending?.target.scene_id ?? null,
      };
    }
    case 'refresh': {
      const selected =
        state.selectedId !== null && action.view.video.scenes[state.selectedId] !== undefined
          ? state.selectedId
          : action.view.video.scene_order[0] ?? null;
      const target =
        state.targetId !== null && action.view.video.scenes[state.targetId] !== undefined
          ? state.targetId
          : null;
      const band =
        action.band === true && selected !== null && state.view !== null
          ? changedFields(state.view.video.scenes[selected], action.view.video.scenes[selected])
          : [];
      return {
        ...state,
        view: action.view,
        selectedId: selected,
        targetId: target,
        band:
          band.length === 0 || selected === null
            ? state.band
            : { sceneId: selected, fields: band, token: (state.band?.token ?? 0) + 1 },
      };
    }
    case 'load-failed':
      return { ...INITIAL, error: action.error ?? 'edit.error.load' };
    case 'select':
      return {
        ...state,
        selectedId: action.id,
        targetId: action.id,
        unseen: state.unseen.filter((id) => id !== action.id),
        band: null,
      };
    case 'target':
      return { ...state, targetId: action.id };
    case 'tab':
      return { ...state, tab: action.tab, band: null };
    case 'unseen':
      return {
        ...state,
        unseen: [...new Set([...state.unseen, ...action.ids])].filter((id) => id !== state.selectedId),
      };
    case 'pending':
      return { ...state, pending: action.plan, pendingSelect: action.selectAfter, preview: { ...INITIAL.preview } };
    case 'pending-cleared':
      return { ...state, pending: null, pendingSelect: null, preview: { ...INITIAL.preview } };
    case 'reorder-review':
      return { ...state, reorder: action.review };
    case 'busy':
      return { ...state, busy: action.value };
    case 'job':
      return {
        ...state,
        job: action.job,
        jobReadFailed: false,
        finishedGeneration: action.job?.id === state.job?.id && action.job?.attempt === state.job?.attempt
          ? state.finishedGeneration
          : null,
      };
    case 'entry-preview-finished':
      return { ...state, job: null, entryPreview: false };
    case 'job-read-failed':
      return { ...state, jobReadFailed: true };
    case 'output-confirmed':
      return { ...state, confirmedForOutput: action.value };
    case 'generation-finished':
      return { ...state, finishedGeneration: action.id };
    case 'chat-job':
      return { ...state, chatJob: action.job };
    case 'message':
      return { ...state, messages: [...state.messages, action.message] };
    case 'sending':
      return { ...state, sending: action.value };
    case 'catalog':
      return {
        ...state,
        sfx: action.sfx,
        voices: action.voices,
        fonts: action.fonts,
        style: action.style,
      };
    case 'bgm':
      return { ...state, bgmStatus: action.status, bgm: action.tracks ?? state.bgm };
    case 'caption-modes':
      return { ...state, captionModes: action.modes };
    case 'action-error':
      return { ...state, actionError: action.error };
    case 'change-errors':
      return { ...state, changeErrors: action.errors };
    case 'preview':
      if (state.pending?.id !== action.planId) return state;
      return { ...state, preview: { ...state.preview, ...action.preview } };
    default:
      return state;
  }
}

export interface SceneProgress {
  id: string;
  state: 'done' | 'running' | 'waiting';
}

/** One settings value the sound and caption tabs write, as a path under the video. */
export interface SettingChange {
  path: string;
  value: unknown;
}

/** What the caption tab reads from the server besides the video itself. */
export interface EditCaption {
  languages: () => Promise<readonly CatalogItem[]>;
  layout: (query: CaptionLayoutQuery) => Promise<CaptionLayout>;
  singleLayer: () => Promise<boolean>;
}

/** What the sound tab needs from the server besides the video itself. */
export interface EditAudio {
  previewUrl: (kind: 'voice' | 'bgm', id: string) => Promise<string | null>;
  uploadBgm: (file: File, mood: Mood) => Promise<Job>;
  generateBgm: (mood: Mood, instruction: string | null) => Promise<Job>;
  readJob: (id: string) => Promise<Job>;
  cancelJob: (id: string) => Promise<Job>;
  reloadBgm: () => Promise<readonly BgmChoice[]>;
}

export interface EditValue {
  active: boolean;
  video: Video | null;
  view: VideoView | null;
  build: VideoView['build'] | null;
  scenes: Scene[];
  selectedId: string | null;
  selectedScene: Scene | null;
  targetId: string | null;
  loading: boolean;
  error: string | null;
  busy: boolean;
  settingsBusy: boolean;
  tab: string;
  canUndo: boolean;
  canStartVideo: boolean;
  unseen: readonly string[];
  /** The cells a chat change touched in the open scene; a new token lights them again. */
  band: SceneBand | null;
  pending: ChangePlan | null;
  pendingPreview: PreviewState;
  reorder: ReorderReview | null;
  phase: EditPhase;
  entryPreview: boolean;
  canPreviewChange: boolean;
  actionError: string | null;
  /** The semantic checks the last rejected change failed, as the server lists them. */
  changeErrors: readonly ErrorItem[];
  dismissError: () => void;
  chatBusy: boolean;
  job: Job | null;
  readonly jobReadFailed: boolean;
  readonly jobWaiting: boolean;
  readonly confirmedForOutput: boolean;
  readonly finishedGeneration: string | null;
  messages: readonly ChatMessage[];
  sending: boolean;
  sfx: readonly CatalogItem[];
  voices: readonly CatalogItem[];
  fonts: readonly CatalogItem[];
  bgm: readonly BgmChoice[];
  bgmStatus: BgmStatus;
  bgmWork: BgmWork;
  captionOptions: { modes: readonly CaptionMode[]; fonts: readonly string[] } | null;
  styleOptions: StyleOptions | null;
  totalSeconds: number;
  progress: { done: number; total: number; scenes: SceneProgress[] };
  stills: { done: number; total: number };
  selectScene: (id: string) => void;
  clearTarget: () => void;
  setTab: (tab: string) => void;
  applyField: (patch: SceneFieldPatch) => void;
  applyLine: (sceneId: string, lineId: string, display: string, speech: string) => void;
  addLine: (sceneId: string, display: string, speech: string) => void;
  addSfx: (sceneId: string, item: CatalogItem) => void;
  applySettings: (changes: readonly SettingChange[]) => void;
  audio: EditAudio;
  caption: EditCaption;
  cancelChat: () => void;
  requestReorderTo: (sceneId: string, toIndex: number) => void;
  confirmReorder: () => void;
  dismissReorder: () => void;
  requestAdd: () => void;
  requestDelete: (sceneId: string) => void;
  applyPending: () => void;
  rejectPending: () => void;
  startPreview: () => void;
  undo: () => void;
  confirmForOutput: () => void;
  acknowledgeOutput: () => void;
  generateVideo: (revision: number) => Promise<boolean>;
  retryGeneration: (job: Job) => Promise<boolean>;
  cancelStills: () => void;
  stopVideo: () => void;
  sendMessage: (text: string) => void;
}

const EditContext = createContext<EditValue | null>(null);

function storageKey(videoId: string): string {
  return `s2s.edit.lastScene.${videoId}`;
}

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // A browser that blocks storage still keeps the selection in memory.
  }
}

export function resetRememberedScene(videoId: string): void {
  try {
    window.localStorage.removeItem(storageKey(videoId));
  } catch {
    // A browser that blocks storage has no saved selection to reset.
  }
}

function scenePreviewKey(videoId: string): string {
  return `s2s.edit.scenePreview.${videoId}`;
}

function readScenePreview(videoId: string): string | null {
  try {
    return window.sessionStorage.getItem(scenePreviewKey(videoId));
  } catch {
    return null;
  }
}

function writeScenePreview(videoId: string, id: string | null): void {
  try {
    if (id === null) window.sessionStorage.removeItem(scenePreviewKey(videoId));
    else window.sessionStorage.setItem(scenePreviewKey(videoId), id);
  } catch {
    // A browser that blocks storage still works for this page.
  }
}

function artifactsFromJob(job: Job): Record<string, string> {
  const artifacts = job.result?.['artifacts'];
  if (artifacts === null || typeof artifacts !== 'object' || !('still' in artifacts)) {
    return {};
  }
  const still = artifacts.still;
  if (still === null || typeof still !== 'object') return {};
  return Object.fromEntries(
    Object.entries(still).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string',
    ),
  );
}

function comparisonResult(job: Job): PreviewState {
  if (jobInFlight(job)) return { job, loading: true, stills: {}, error: null };
  if (job.state === 'succeeded') return { job, loading: false, stills: artifactsFromJob(job), error: null };
  return { job, loading: false, stills: {}, error: 'edit.change.previewFailed' };
}

function changeIdFromJob(job: Job): string | null {
  const changeId = job.result?.['change_id'];
  return typeof changeId === 'string' ? changeId : null;
}

function unsupportedFromJob(job: Job): string[] {
  const unsupported = job.result?.['unsupported'];
  return Array.isArray(unsupported)
    ? unsupported.filter((item): item is string => typeof item === 'string')
    : [];
}

function notesFromJob(job: Job): string {
  const notes = job.result?.['notes'];
  return Array.isArray(notes) ? notes.filter((note): note is string => typeof note === 'string').join(' ') : '';
}

function canPreviewStage(view: VideoView | null): boolean {
  return view?.video.stage === 'script_confirmed' || view?.video.stage === 'scenes_confirmed';
}

export function isAudioSettingsChange(ops: ChangePlan['ops']): boolean {
  return ops.length > 0 && ops.every((op) => op.op === 'set' &&
    [VOICE_PATH, BGM_PATH].some((path) => op.path === path || op.path.startsWith(`${path}/`)),
  );
}

function jobInFlight(job: Job): boolean {
  return job.state === 'queued' || job.state === 'running' || job.state === 'cancelling';
}

function selectedAfter(view: VideoView, id: string | null): string | null {
  if (id !== null && view.video.scenes[id] !== undefined) return id;
  return view.video.scene_order[0] ?? null;
}

function newBlankScene(id: string): Scene {
  return {
    id,
    beat_id: 'new',
    beat_label: '새 장면',
    lines: [
      {
        id: newLocalId('l'),
        display_text: '새 장면의 대사를 적어 주세요.',
        speech_text: '새 장면의 대사를 적어 주세요.',
        speaker: 'narrator',
        highlight: [],
      },
    ],
    visual: {
      background_id: 'bg_village',
      characters: [],
      elements: [],
      sfx: [],
      transition_in: 'cut',
    },
  } as Scene;
}

export function EditProvider({
  active,
  videoId,
  previewOnEntry = false,
  api: providedApi,
  children,
}: {
  active: boolean;
  previewOnEntry?: boolean;
  videoId: string | null;
  api?: EditApi;
  children: ReactNode;
}) {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const api = useMemo(() => providedApi ?? createEditApi(), [providedApi]);
  const videoEpoch = useRef(0);
  const jobPoll = useRef(0);
  const chatPoll = useRef(0);
  const previewPoll = useRef(0);
  const chatStopping = useRef(false);
  const scenePreview = useRef<string | null>(null);
  const previewEntryEnabled = useRef(previewOnEntry);
  const chatQueue = useRef<ChatRequest[]>([]);
  const revisionRef = useRef<number | null>(null);
  const generationSubmitting = useRef(false);
  const stoppedLogged = useRef<string | null>(null);

  const load = useMemo(() => async (id: string): Promise<VideoView> => api.load(id), [api]);

  useEffect(() => {
    revisionRef.current = state.view?.video.revision ?? null;
  }, [state.view?.video.revision]);

  useEffect(() => {
    previewEntryEnabled.current = previewOnEntry;
  }, [previewOnEntry]);

  const logChatResult = useCallback((result: Omit<ChatMessage, 'id' | 'role'>) => {
    dispatch({ type: 'message', message: { id: newLocalId('l'), role: 'assistant', ...result } });
  }, []);

  const stopChatJob = useCallback((job: Job) => {
    const epoch = videoEpoch.current;
    const token = ++chatPoll.current;
    void api.cancelJob(job.id).then((next) => {
      if (epoch === videoEpoch.current && token === chatPoll.current) {
        dispatch({ type: 'chat-job', job: next });
      }
    }).catch((error: unknown) => {
      if (epoch !== videoEpoch.current || token !== chatPoll.current) return;
      chatStopping.current = false;
      // The job may have finished just before cancel reached the server.
      // Poll again to consume the actual terminal result.
      if (!(error instanceof EditApiError && error.code === 'job_terminal')) {
        dispatch({ type: 'action-error', error: 'edit.error.stop' });
      }
      dispatch({ type: 'chat-job', job: { ...job } });
    });
  }, [api]);

  const startChat = useCallback(
    (request: ChatRequest) => {
      const revision = revisionRef.current;
      if (videoId === null || revision === null) return;
      const epoch = videoEpoch.current;
      chatStopping.current = false;
      dispatch({ type: 'sending', value: true });
      void api
        .sendMessage(videoId, {
          base_revision: revision,
          text: request.text,
          target: { scene_id: request.target, pointer: null },
        })
        .then((job) => {
          if (epoch !== videoEpoch.current) return;
          if (chatStopping.current && jobInFlight(job)) stopChatJob(job);
          else dispatch({ type: 'chat-job', job });
        })
        .catch(() => {
          if (epoch !== videoEpoch.current) return;
          dispatch({ type: 'sending', value: false });
          logChatResult({ kind: 'error' });
        });
    },
    [api, logChatResult, stopChatJob, videoId],
  );

  useEffect(() => {
    if (!active || videoId === null) return undefined;
    const epoch = ++videoEpoch.current;
    scenePreview.current = null;
    chatStopping.current = false;
    chatQueue.current = [];
    let cancelled = false;
    dispatch({ type: 'loading' });
    void load(videoId)
      .then(async (view) => {
        if (cancelled || epoch !== videoEpoch.current) return;
        const pending = view.pending_change === null ? null : await api.readChange(view.pending_change);
        if (cancelled || epoch !== videoEpoch.current) return;
        const selected = selectedFor(view, readStorage(storageKey(videoId)));
        let resumed: Job | null = null;
        let resumeFailed = false;
        let entryPreview = false;
        const ownPreview = readScenePreview(videoId);
        for (const jobId of view.open_jobs) {
          let open: Job;
          try {
            open = await api.readJob(jobId);
          } catch {
            resumeFailed = true;
            continue;
          }
          if (open.kind === 'generate') {
            resumed = open;
            entryPreview = false;
            break;
          }
          if (open.kind === 'preview' && (ownPreview === open.id || ownPreview === `entry:${open.id}`)) {
            resumed = open;
            entryPreview = ownPreview !== open.id;
            scenePreview.current = open.id;
          }
        }
        if (cancelled || epoch !== videoEpoch.current) return;
        const buildOnEntry = previewEntryEnabled.current && canPreviewStage(view) &&
          resumed === null && view.open_jobs.length === 0 && pending?.status !== 'proposed' &&
          selected !== null && !stillIsReady(view.build, selected) &&
          view.build.scenes[selected]?.still.state !== 'failed';
        dispatch({
          type: 'loaded',
          view,
          selected,
          pending: pending?.status === 'proposed' ? pending : null,
          job: resumed,
          entryPreview: entryPreview || buildOnEntry,
        });
        if (resumeFailed && resumed === null) dispatch({ type: 'action-error', error: 'edit.error.resume' });
        if (buildOnEntry) {
          const missing = view.video.scene_order.filter((id) => !stillIsReady(view.build, id));
          void api.previewScenes(videoId, view.video.revision, missing).then((job) => {
            if (cancelled || epoch !== videoEpoch.current) return;
            scenePreview.current = job.id;
            writeScenePreview(videoId, `entry:${job.id}`);
            dispatch({ type: 'job', job });
          }).catch(() => {
            if (cancelled || epoch !== videoEpoch.current) return;
            dispatch({ type: 'entry-preview-finished' });
            dispatch({ type: 'action-error', error: 'edit.error.videoStart' });
          });
        }
        const styleRef = view.video.settings.visual.art_style;
        const styleId = typeof styleRef?.id === 'string' ? styleRef.id : '';
        const themeId = typeof view.video.settings.visual.theme_id === 'string' ? view.video.settings.visual.theme_id : '';
        const [sfx, voices, fonts, style] = await Promise.all([
          api.listCatalog('sfx', videoId).catch(() => []),
          api.listCatalog('voice', videoId).catch(() => []),
          api.listCatalog('font', videoId).catch(() => []),
          api.styleOptions(styleId, themeId).catch(() => null),
        ]);
        if (!cancelled && epoch === videoEpoch.current) {
          dispatch({ type: 'catalog', sfx, voices, fonts, style });
        }
      })
      .catch(() => {
        if (!cancelled && epoch === videoEpoch.current) dispatch({ type: 'load-failed' });
      });
    return () => {
      cancelled = true;
      if (videoEpoch.current === epoch) videoEpoch.current += 1;
    };
  }, [active, api, load, videoId]);

  const rememberSelection = useCallback((id: string) => {
    dispatch({ type: 'select', id });
    if (videoId !== null) writeStorage(storageKey(videoId), id);
  }, [videoId]);

  const refresh = useMemo(
    () => async (selectAfter: string | null = null, band = false) => {
      if (videoId === null) return;
      const epoch = videoEpoch.current;
      const view = await api.load(videoId);
      if (epoch !== videoEpoch.current) return;
      revisionRef.current = view.video.revision;
      dispatch({ type: 'refresh', view, band });
      if (selectAfter !== null) {
        const next = selectedAfter(view, selectAfter);
        if (next !== null) rememberSelection(next);
      }
    },
    [api, rememberSelection, videoId],
  );

  const watchedJobId = state.job !== null && jobInFlight(state.job) ? state.job.id : null;
  useEffect(() => {
    if (watchedJobId === null) return undefined;
    const epoch = videoEpoch.current;
    const token = ++jobPoll.current;
    let timer: number;
    const tick = async () => {
      try {
        const job = await api.readJob(watchedJobId);
        if (token !== jobPoll.current || epoch !== videoEpoch.current) return;
        dispatch({ type: 'job', job });
        if (!jobInFlight(job)) return;
      } catch {
        if (token !== jobPoll.current || epoch !== videoEpoch.current) return;
        dispatch({ type: 'job-read-failed' });
      }
      timer = window.setTimeout(() => void tick(), 250);
    };
    timer = window.setTimeout(() => void tick(), 250);
    return () => {
      jobPoll.current += 1;
      window.clearTimeout(timer);
    };
  }, [api, watchedJobId]);

  useEffect(() => {
    const job = state.job;
    if (job === null) return undefined;
    if (state.entryPreview && job.kind === 'preview' && !jobInFlight(job)) {
      let cancelled = false;
      const epoch = videoEpoch.current;
      const finish = () => {
        if (cancelled || epoch !== videoEpoch.current) return;
        scenePreview.current = null;
        if (videoId !== null) writeScenePreview(videoId, null);
        dispatch({ type: 'entry-preview-finished' });
      };
      if (job.state === 'failed') dispatch({ type: 'action-error', error: 'edit.error.videoStart' });
      void refresh().catch(() => {
        if (!cancelled && epoch === videoEpoch.current) {
          dispatch({ type: 'action-error', error: 'edit.error.load' });
        }
      }).finally(finish);
      return () => { cancelled = true; };
    }
    if (job.kind === 'preview' && job.state === 'succeeded' && scenePreview.current === job.id) {
      let cancelled = false;
      const epoch = videoEpoch.current;
      void (async () => {
        try {
          if (videoId === null) return;
          const loaded = await api.load(videoId);
          if (cancelled || epoch !== videoEpoch.current) return;
          await api.confirmScenes(videoId, loaded.video.revision);
          if (cancelled || epoch !== videoEpoch.current) return;
          await refresh();
          if (cancelled || epoch !== videoEpoch.current) return;
          scenePreview.current = null;
          writeScenePreview(videoId, null);
          dispatch({ type: 'job', job: null });
          dispatch({ type: 'output-confirmed', value: true });
        } catch {
          if (cancelled || epoch !== videoEpoch.current) return;
          dispatch({ type: 'action-error', error: 'edit.error.videoStart' });
          dispatch({ type: 'job', job: null });
        }
      })();
      return () => {
        cancelled = true;
      };
    }
    if (job.kind === 'generate') {
      if (job.state === 'succeeded') {
        let cancelled = false;
        void refresh().then(() => {
          if (!cancelled) dispatch({ type: 'generation-finished', id: job.id });
        }).catch(() => {
          if (!cancelled) {
            dispatch({ type: 'job-read-failed' });
            dispatch({ type: 'generation-finished', id: job.id });
          }
        });
        return () => { cancelled = true; };
      }
      if (job.state === 'failed' || job.state === 'cancelled') {
        const attempt = `${job.id}:${job.attempt}`;
        if (job.state === 'cancelled' && stoppedLogged.current !== attempt) {
          stoppedLogged.current = attempt;
          logChatResult({ kind: 'videoStopped' });
        }
        dispatch({ type: 'generation-finished', id: job.id });
      }
    } else if (job.state === 'failed') {
      dispatch({ type: 'action-error', error: 'edit.error.videoStart' });
    } else if (job.state === 'cancelled') {
      dispatch({ type: 'job', job: null });
    }
    return undefined;
  }, [api, logChatResult, refresh, state.entryPreview, state.job, videoId]);

  useEffect(() => {
    const initial = state.chatJob;
    if (!active || initial === null) return undefined;
    const epoch = videoEpoch.current;
    const token = ++chatPoll.current;
    const current = () => token === chatPoll.current && epoch === videoEpoch.current;
    let timer: number | undefined;
    const poll = () => {
      timer = window.setTimeout(() => {
        if (current()) void api.readJob(initial.id).then(consume).catch(fail);
      }, 250);
    };
    const finish = () => {
      dispatch({ type: 'chat-job', job: null });
      dispatch({ type: 'sending', value: false });
      chatStopping.current = false;
    };
    const fail = () => {
      if (!current()) return;
      logChatResult({ kind: 'error' });
      finish();
    };
    const consume = async (job: Job) => {
      if (!current()) return;
      if (jobInFlight(job)) {
        poll();
        return;
      }
      if (job.state !== 'succeeded') {
        logChatResult({ kind: job.state === 'cancelled' ? 'cancelled' : 'error' });
        finish();
        return;
      }
      const unsupported = unsupportedFromJob(job);
      const changeId = changeIdFromJob(job);
      if (changeId !== null) {
        const plan = await api.readChange(changeId);
        if (!current()) return;
        const sceneIds = isAudioSettingsChange(plan.ops) ? [] :
          [...new Set([...plan.effects.scene_ids_render, ...plan.effects.scene_ids_text])];
        if (plan.status === 'proposed') {
          dispatch({ type: 'pending', plan, selectAfter: plan.target.scene_id });
        } else if (plan.status === 'applied' || plan.status === 'stale') {
          await refresh(null, plan.status === 'applied');
          if (!current()) return;
          if (plan.status === 'applied') dispatch({ type: 'unseen', ids: sceneIds });
        }
        if (plan.status === 'proposed' || plan.status === 'applied') {
          logChatResult({
            kind: plan.status,
            targetId: plan.target.scene_id,
            sceneIds,
            detail: notesFromJob(job),
          });
        } else {
          logChatResult({ kind: plan.status === 'stale' ? 'stale' : 'error' });
        }
      } else if (unsupported.length === 0) {
        logChatResult({ kind: 'noChange', detail: notesFromJob(job) });
      }
      if (unsupported.length > 0) {
        logChatResult({ kind: 'unsupported', detail: unsupported.join(' ') });
      }
      finish();
    };
    void consume(initial).catch(fail);
    return () => {
      if (chatPoll.current === token) chatPoll.current += 1;
      window.clearTimeout(timer);
    };
  }, [active, api, logChatResult, refresh, state.chatJob]);

  useEffect(() => {
    if (!active || state.view === null || state.sending || state.busy || state.entryPreview ||
      state.pending !== null || state.reorder !== null) return;
    const next = chatQueue.current.shift();
    if (next !== undefined) startChat(next);
  }, [active, startChat, state.view, state.sending, state.busy, state.entryPreview, state.pending, state.reorder]);

  useEffect(() => {
    if (state.preview.job === null) return undefined;
    const job = state.preview.job;
    if (!jobInFlight(job)) return undefined;
    const planId = state.pending?.id;
    if (planId === undefined) return undefined;
    const epoch = videoEpoch.current;
    const token = ++previewPoll.current;
    let stopped = false;
    const timer = window.setInterval(() => {
      void api.readJob(job.id).then((next) => {
        if (stopped || token !== previewPoll.current || epoch !== videoEpoch.current) return;
        if (!jobInFlight(next)) dispatch({ type: 'preview', planId, preview: comparisonResult(next) });
      }).catch(() => {
        if (stopped || token !== previewPoll.current) return;
        dispatch({ type: 'preview', planId, preview: { job: null, loading: false, error: 'edit.change.previewFailed' } });
      });
    }, 300);
    return () => {
      stopped = true;
      if (previewPoll.current === token) previewPoll.current += 1;
      window.clearInterval(timer);
    };
  }, [api, state.pending?.id, state.preview.job]);

  const scenes = useMemo(() => scenesOf(state.view?.video ?? null), [state.view]);
  const selectedScene = useMemo(
    () =>
      state.selectedId === null || state.view === null
        ? null
        : state.view.video.scenes[state.selectedId] ?? null,
    [state.selectedId, state.view],
  );
  const phase = phaseOf(state.job, state.view, state.entryPreview, state.finishedGeneration);
  const videoProgress = sceneProgress(state.job, 'clip', scenes.length);
  const stillProgress = sceneProgress(state.job, 'still', scenes.length);
  const { done, total } = videoProgress;
  const { done: stillDone, total: stillTotal } = stillProgress;
  const clipRunning = phase === 'video' && state.job?.stages.some(
    (stage) => stage.stage === 'clip' && stage.state === 'running',
  );

  const loadedVideo = state.view?.video;
  const loadedVideoId = loadedVideo?.id;
  const layoutId = loadedVideo?.settings.format.layout?.id;
  const bgmRequest = useRef(0);
  const reloadBgm = useCallback(async () => {
    if (!active || videoId === null || videoId !== loadedVideoId) return [];
    const epoch = videoEpoch.current;
    const request = ++bgmRequest.current;
    const current = () => epoch === videoEpoch.current && request === bgmRequest.current;
    dispatch({ type: 'bgm', status: 'loading' });
    try {
      const tracks = await api.listBgm(videoId);
      if (current()) dispatch({ type: 'bgm', status: 'ready', tracks });
      return tracks;
    } catch (failure) {
      if (current()) dispatch({ type: 'bgm', status: 'failed' });
      throw failure;
    }
  }, [active, api, loadedVideoId, videoId]);

  useEffect(() => {
    void reloadBgm().catch(() => { /* The catalog state carries the failure. */ });
  }, [reloadBgm]);

  useEffect(() => {
    if (!active || loadedVideoId !== videoId) return;
    let current = true;
    dispatch({ type: 'caption-modes', modes: null });
    void api.templateCaptionModes(layoutId ?? '').then((modes) => {
      if (current) dispatch({ type: 'caption-modes', modes });
    }).catch(() => { /* No compatibility data means no new selection. */ });
    return () => { current = false; };
  }, [active, api, layoutId, loadedVideoId, videoId]);

  const value = useMemo<Omit<EditValue, 'bgmWork'>>(() => {
    const progressScenes: SceneProgress[] = scenes.map((scene, index) => ({
      id: scene.id,
      state:
        index < done
          ? 'done'
          : index === done && clipRunning
            ? 'running'
            : 'waiting',
    }));

    const selectScene = (id: string) => {
      if (state.view?.video.scenes[id] === undefined) return;
      rememberSelection(id);
    };

    const submitChange = (
      ops: ChangePlan['ops'],
      selectAfter: string | null = null,
      targetScene: string | null = state.selectedId,
    ) => {
      if (videoId === null || state.view === null || state.entryPreview) return;
      const revision = state.view.video.revision;
      const audioOnly = isAudioSettingsChange(ops);
      const epoch = videoEpoch.current;
      dispatch({ type: 'busy', value: true });
      dispatch({ type: 'change-errors', errors: [] });
      void api
        .change(videoId, {
          base_revision: revision,
          source: 'direct',
          target: { scene_id: targetScene, pointer: null },
          ops,
        })
        .then(async (plan) => {
          if (epoch !== videoEpoch.current) return;
          if (plan.status === 'proposed' && audioOnly &&
              plan.effects.locked_keys.length === 0 && plan.effects.overwrites_user_values.length === 0) {
            await api.applyChange(plan.id, revision);
            if (epoch !== videoEpoch.current) return;
            await refresh();
            return;
          }
          if (plan.status === 'proposed') {
            dispatch({ type: 'pending', plan, selectAfter });
          } else if (plan.status === 'applied') {
            if (!audioOnly) {
              const affected = plan.effects.scene_ids_render.length > 0
                ? plan.effects.scene_ids_render
                : plan.effects.scene_ids_text;
              dispatch({ type: 'unseen', ids: affected });
            }
            await refresh(selectAfter);
          } else {
            dispatch({ type: 'action-error', error: 'edit.error.change' });
          }
        })
        .catch((failure: unknown) => {
          if (epoch !== videoEpoch.current) return;
          if (failure instanceof EditApiError) dispatch({ type: 'change-errors', errors: failure.errors });
          dispatch({ type: 'action-error', error: 'edit.error.change' });
        })
        .finally(() => {
          if (epoch === videoEpoch.current) dispatch({ type: 'busy', value: false });
        });
    };

    const applyField = (patch: SceneFieldPatch) => {
      if (selectedScene === null) return;
      if (
        (patch.kind === 'expression' || patch.kind === 'position') &&
        (selectedScene.visual?.characters.length ?? 0) === 0
      ) {
        return;
      }
      submitChange(sceneFieldOps(selectedScene, patch));
    };

    const applyLine = (sceneId: string, lineId: string, display: string, speech: string) => {
      const scene = state.view?.video.scenes[sceneId];
      if (scene === undefined || display.trim() === '' || speech.trim() === '') return;
      const length = Array.from(display).length;
      const lines = scene.lines.map((line: Line) =>
        line.id === lineId
          ? {
              ...line,
              display_text: display,
              speech_text: speech,
              highlight: line.highlight
                .map((span) => ({ start: Math.min(span.start, length), end: Math.min(span.end, length) }))
                .filter((span) => span.start < span.end),
            }
          : line,
      );
      submitChange([{ op: 'set', path: `/scenes/${sceneId}/lines`, value: lines, origin: 'user' }], null, sceneId);
    };

    const addLine = (sceneId: string, display: string, speech: string) => {
      const scene = state.view?.video.scenes[sceneId];
      if (scene === undefined || scene.lines.length >= MAX_LINES_PER_SCENE) return;
      if (display.trim() === '' || speech.trim() === '') return;
      const line: Line = {
        id: newLocalId('l'),
        display_text: display,
        speech_text: speech,
        speaker: 'narrator',
        highlight: [],
      };
      submitChange(
        [{ op: 'set', path: `/scenes/${sceneId}/lines`, value: [...scene.lines, line], origin: 'user' }],
        null,
        sceneId,
      );
    };

    const addSfx = (sceneId: string, item: CatalogItem) => {
      const scene = state.view?.video.scenes[sceneId];
      if (scene === undefined || (scene.visual?.sfx.length ?? 0) >= 2) return;
      const line = scene.lines[0];
      if (line === undefined) return;
      const cue = {
        sfx_id: { id: item.id, revision: item.revision },
        line_id: line.id,
        at: 'start' as const,
        offset_ms: 0,
      };
      const cues = [...(scene.visual?.sfx ?? []), cue];
      submitChange([{ op: 'set', path: `/scenes/${sceneId}/visual/sfx`, value: cues, origin: 'user' }], null, sceneId);
    };

    const settingsBusy = state.busy || state.entryPreview || state.sending || state.pending !== null ||
      state.reorder !== null || chatQueue.current.length > 0;
    const applySettings = (changes: readonly SettingChange[]) => {
      if (state.view === null || changes.length === 0) return;
      if (settingsBusy) return;
      submitChange(
        changes.map((change) => ({
          op: 'set' as const,
          path: change.path,
          value: change.value,
          origin: 'user' as const,
        })),
        null,
        null,
      );
    };

    const caption: EditCaption = {
      languages: async () => (videoId === null ? [] : api.listCatalog('caption_language', videoId)),
      layout: (query) => {
        if (videoId === null) return Promise.reject(new EditApiError('not_found', 404, 'video'));
        return api.captionLayout(videoId, query);
      },
      singleLayer: () => api.templateSingleLayer(layoutId ?? ''),
    };

    const audio: EditAudio = {
      previewUrl: (kind, id) => api.previewUrl(kind, id),
      uploadBgm: (file, mood) => {
        if (state.view === null) return Promise.reject(new EditApiError('not_found', 404, 'video'));
        return api.uploadBgm(state.view.video.project_id, file, mood);
      },
      generateBgm: (mood, instruction) => {
        if (state.view === null) return Promise.reject(new EditApiError('not_found', 404, 'video'));
        return api.createBgmCode(state.view.video.project_id, mood, instruction);
      },
      readJob: (id) => api.readJob(id),
      cancelJob: (id) => api.cancelJob(id),
      reloadBgm,
    };

    const requestReorder = (order: readonly string[]) => {
      if (state.view === null || state.busy || state.entryPreview || state.sending || state.pending !== null) return;
      if (order.length !== state.view.video.scene_order.length) return;
      if (order.every((id, index) => id === state.view?.video.scene_order[index])) return;
      dispatch({ type: 'reorder-review', review: { order: [...order], revision: state.view.video.revision } });
    };

    const requestReorderTo = (sceneId: string, toIndex: number) => {
      if (state.view === null) return;
      requestReorder(moveScene(state.view.video.scene_order, sceneId, toIndex));
    };

    const requestAdd = () => {
      if (state.view === null) return;
      const sourceId = state.selectedId ?? state.view.video.scene_order.at(-1) ?? null;
      const source = sourceId === null ? null : state.view.video.scenes[sourceId] ?? null;
      const id = newLocalId('s');
      const scene = source === null ? newBlankScene(id) : duplicateScene(state.view.video, source.id, id);
      if (scene === null) return;
      const anchor = sourceId;
      submitChange([{ op: 'add_scene', after: anchor, scene }], scene.id);
    };

    const requestDelete = (sceneId: string) => {
      if (state.view === null || state.view.video.scenes[sceneId] === undefined) return;
      const index = state.view.video.scene_order.indexOf(sceneId);
      const next = state.view.video.scene_order[index + 1] ?? state.view.video.scene_order[index - 1] ?? null;
      submitChange([{ op: 'remove_scene', scene_id: sceneId }], next);
    };

    const applyPending = () => {
      const plan = state.pending;
      if (plan === null || state.view === null) return;
      const epoch = videoEpoch.current;
      dispatch({ type: 'busy', value: true });
      void api
        .applyChange(plan.id, state.view.video.revision)
        .then(async (video) => {
          if (epoch !== videoEpoch.current) return;
          revisionRef.current = video.revision;
          dispatch({ type: 'pending-cleared' });
          await refresh(state.pendingSelect);
        })
        .catch(() => {
          if (epoch === videoEpoch.current) dispatch({ type: 'action-error', error: 'edit.error.change' });
        })
        .finally(() => {
          if (epoch === videoEpoch.current) dispatch({ type: 'busy', value: false });
        });
    };

    const rejectPending = () => {
      const plan = state.pending;
      if (plan === null) return;
      const epoch = videoEpoch.current;
      dispatch({ type: 'busy', value: true });
      void api
        .rejectChange(plan.id)
        .then(async () => {
          if (epoch !== videoEpoch.current) return;
          dispatch({ type: 'pending-cleared' });
          await refresh();
        })
        .catch(() => {
          if (epoch === videoEpoch.current) dispatch({ type: 'action-error', error: 'edit.error.change' });
        })
        .finally(() => {
          if (epoch === videoEpoch.current) dispatch({ type: 'busy', value: false });
        });
    };

    const startPreview = () => {
      const plan = state.pending;
      if (plan === null || state.preview.loading) return;
      if (!canPreviewStage(state.view)) return;
      const epoch = videoEpoch.current;
      const planId = plan.id;
      dispatch({ type: 'preview', planId, preview: { job: null, loading: true, error: null, stills: {} } });
      void api
        .previewChange(plan.id)
        .then((job) => {
          if (epoch !== videoEpoch.current) return;
          dispatch({ type: 'preview', planId, preview: comparisonResult(job) });
        })
        .catch(() => {
          if (epoch === videoEpoch.current) {
            dispatch({ type: 'preview', planId, preview: { loading: false, error: 'edit.change.previewFailed' } });
          }
        });
    };

    const undo = () => {
      if (state.view === null || videoId === null) return;
      if (state.view.video.created_by === 'undo') return;
      const epoch = videoEpoch.current;
      dispatch({ type: 'busy', value: true });
      void api
        .undo(videoId, state.view.video.revision)
        .then(async () => {
          await refresh(state.selectedId);
          if (epoch === videoEpoch.current) dispatch({ type: 'unseen', ids: [] });
        })
        .catch(() => {
          if (epoch === videoEpoch.current) dispatch({ type: 'action-error', error: 'edit.error.undo' });
        })
        .finally(() => {
          if (epoch === videoEpoch.current) dispatch({ type: 'busy', value: false });
        });
    };

    const confirmForOutput = () => {
      if (state.view === null || videoId === null || state.entryPreview) return;
      const stage = state.view.video.stage;
      const epoch = videoEpoch.current;
      if (stage === 'script_confirmed') {
        void api
          .previewScenes(videoId, state.view.video.revision, state.view.video.scene_order)
          .then((job) => {
            if (epoch !== videoEpoch.current) return;
            scenePreview.current = job.id;
            writeScenePreview(videoId, job.id);
            dispatch({ type: 'job', job });
          })
          .catch(() => {
            if (epoch === videoEpoch.current) dispatch({ type: 'action-error', error: 'edit.error.videoStart' });
          });
        return;
      }
      if (stage !== 'scenes_confirmed') {
        dispatch({ type: 'action-error', error: 'edit.error.notConfirmed' });
        return;
      }
      dispatch({ type: 'output-confirmed', value: true });
    };

    const submitGeneration = async (submit: () => Promise<Job>) => {
      if (generationSubmitting.current || (state.job !== null && jobInFlight(state.job))) return false;
      generationSubmitting.current = true;
      const epoch = videoEpoch.current;
      try {
        const job = await submit();
        if (epoch !== videoEpoch.current) return false;
        dispatch({ type: 'job', job });
        return true;
      } catch (error) {
        if (error instanceof ApiProblemError && error.code === 'job_not_retryable') throw error;
        return false;
      } finally {
        generationSubmitting.current = false;
      }
    };

    const generateVideo = (revision: number) =>
      videoId !== null &&
        state.view?.video.stage === 'scenes_confirmed' &&
        state.view.video.revision === revision
        ? submitGeneration(() => api.generate(videoId, revision))
        : Promise.resolve(false);

    const retryGeneration = (job: Job) =>
      videoId !== null && job.video_id === videoId && job.kind === 'generate'
        ? submitGeneration(() => retryJob(job.id))
        : Promise.resolve(false);

    const cancelJob = () => {
      const job = state.job;
      if (job === null) return;
      const epoch = videoEpoch.current;
      const token = jobPoll.current;
      void api
        .cancelJob(job.id)
        .then((next) => {
          if (epoch === videoEpoch.current && token === jobPoll.current) {
            if (job.kind === 'preview' && next.state === 'cancelled') {
              scenePreview.current = null;
              if (videoId !== null) writeScenePreview(videoId, null);
            }
            dispatch({ type: 'job', job: next });
          }
        })
        .catch(() => {
          if (epoch !== videoEpoch.current) return;
          dispatch({ type: 'action-error', error: 'edit.error.stop' });
          if (state.job?.id === job.id) dispatch({ type: 'job', job: { ...job } });
        });
    };

    const cancelChat = () => {
      if (chatQueue.current.length > 0) {
        chatQueue.current = [];
        logChatResult({ kind: 'queueDiscarded' });
      }
      if (chatStopping.current) return;
      chatStopping.current = true;
      // While POST is in flight, startChat will stop the job once it has its ID.
      if (state.chatJob !== null && jobInFlight(state.chatJob)) stopChatJob(state.chatJob);
    };

    const sendMessage = (text: string) => {
      const message = text.trim();
      if (message === '' || state.view === null || videoId === null) return;
      const target = state.targetId;
      const id = newLocalId('l');
      dispatch({ type: 'message', message: { id: `${id}u`, role: 'user', text: message, targetId: target } });
      if (state.sending || state.busy || state.entryPreview || state.pending !== null ||
        state.reorder !== null || chatQueue.current.length > 0) {
        chatQueue.current.push({ text: message, target });
        return;
      }
      startChat({ text: message, target });
    };

    return {
      active,
      video: state.view?.video ?? null,
      view: state.view,
      build: state.view?.build ?? null,
      scenes,
      selectedId: state.selectedId,
      selectedScene,
      targetId: state.targetId,
      loading: state.loading,
      error: state.error,
      busy: state.busy,
      settingsBusy,
      tab: state.tab,
      canUndo:
        state.view !== null &&
        state.view.video.parent_revision !== null &&
        state.view.video.created_by !== 'undo',
      canStartVideo:
        (state.view?.video.stage === 'script_confirmed' || state.view?.video.stage === 'scenes_confirmed') &&
        scenes.length > 0,
      canPreviewChange:
        state.view?.video.stage === 'script_confirmed' || state.view?.video.stage === 'scenes_confirmed',
      actionError: state.actionError,
      changeErrors: state.changeErrors,
      dismissError: () => dispatch({ type: 'action-error', error: null }),
      chatBusy: state.sending,
      unseen: state.unseen,
      band: state.band,
      pending: state.pending,
      pendingPreview: state.preview,
      reorder: state.reorder,
      phase,
      entryPreview: state.entryPreview,
      job: state.job,
      jobReadFailed: state.jobReadFailed,
      jobWaiting: (state.job !== null && jobInFlight(state.job)) ||
        (state.chatJob !== null && jobInFlight(state.chatJob)) ||
        (state.preview.job !== null && jobInFlight(state.preview.job)),
      confirmedForOutput: state.confirmedForOutput,
      finishedGeneration: state.finishedGeneration,
      messages: state.messages,
      sending: state.sending,
      sfx: state.sfx,
      voices: state.voices,
      fonts: state.fonts,
      bgm: state.bgm,
      bgmStatus: state.bgmStatus,
      captionOptions: state.captionModes === null || state.style === null
        ? null
        : { modes: state.captionModes, fonts: state.style.fonts },
      styleOptions: state.style,
      totalSeconds:
        state.view !== null && state.view.build.estimated_ms > 0
          ? Math.round(state.view.build.estimated_ms / 1000)
          : totalEstimatedSeconds(scenes),
      progress: { done, total, scenes: progressScenes },
      stills: { done: stillDone, total: stillTotal },
      selectScene,
      clearTarget: () => dispatch({ type: 'target', id: null }),
      setTab: (tab: string) => dispatch({ type: 'tab', tab }),
      applyField,
      applyLine,
      addLine,
      addSfx,
      applySettings,
      audio,
      caption,
      requestReorderTo,
      confirmReorder: () => {
        const review = state.reorder;
        if (review === null) return;
        dispatch({ type: 'reorder-review', review: null });
        if (state.view?.video.revision !== review.revision) {
          dispatch({ type: 'action-error', error: 'edit.error.change' });
          return;
        }
        submitChange([{ op: 'reorder', order: review.order }], null, null);
      },
      dismissReorder: () => dispatch({ type: 'reorder-review', review: null }),
      requestAdd,
      requestDelete,
      applyPending,
      rejectPending,
      startPreview,
      undo,
      confirmForOutput,
      acknowledgeOutput: () => dispatch({ type: 'output-confirmed', value: false }),
      generateVideo,
      retryGeneration,
      cancelStills: cancelJob,
      stopVideo: cancelJob,
      sendMessage,
      cancelChat,
    };
  }, [
    active,
    api,
    clipRunning,
    done,
    layoutId,
    logChatResult,
    phase,
    refresh,
    reloadBgm,
    rememberSelection,
    scenes,
    selectedScene,
    startChat,
    stopChatJob,
    state,
    stillDone,
    stillTotal,
    total,
    videoId,
  ]);

  const bgmWork = useBgmWork(value);
  return <EditContext.Provider value={{ ...value, bgmWork }}>{children}</EditContext.Provider>;
}

export function useEdit(): EditValue {
  const value = useContext(EditContext);
  if (value === null) {
    throw new Error('useEdit must be used inside EditProvider');
  }
  return value;
}

export function useEditOptional(): EditValue | null {
  return useContext(EditContext);
}

export const EMPTY_EDIT_VALUE: EditValue = {
  active: false,
  video: null,
  view: null,
  build: null,
  scenes: [],
  selectedId: null,
  selectedScene: null,
  targetId: null,
  loading: false,
  error: null,
  busy: false,
  settingsBusy: false,
  tab: 'scenes',
  canUndo: false,
  canStartVideo: false,
  canPreviewChange: false,
  actionError: null,
  changeErrors: [],
  dismissError: () => undefined,
  chatBusy: false,
  unseen: [],
  band: null,
  pending: null,
  pendingPreview: { job: null, stills: {}, loading: false, error: null },
  reorder: null,
  phase: 'idle',
  entryPreview: false,
  job: null,
  jobReadFailed: false,
  jobWaiting: false,
  confirmedForOutput: false,
  finishedGeneration: null,
  messages: [],
  sending: false,
  sfx: [],
  voices: [],
  fonts: [],
  bgm: [],
  bgmStatus: 'loading',
  bgmWork: EMPTY_BGM_WORK,
  captionOptions: null,
  styleOptions: null,
  totalSeconds: 0,
  progress: { done: 0, total: 0, scenes: [] },
  stills: { done: 0, total: 0 },
  selectScene: () => undefined,
  clearTarget: () => undefined,
  setTab: () => undefined,
  applyField: () => undefined,
  applyLine: () => undefined,
  addLine: () => undefined,
  addSfx: () => undefined,
  applySettings: () => undefined,
  audio: {
    previewUrl: () => Promise.resolve(null),
    uploadBgm: () => Promise.reject(new Error('no video is open')),
    generateBgm: () => Promise.reject(new Error('no video is open')),
    readJob: () => Promise.reject(new Error('no video is open')),
    cancelJob: () => Promise.reject(new Error('no video is open')),
    reloadBgm: () => Promise.resolve([]),
  },
  caption: {
    languages: () => Promise.resolve([]),
    layout: () => Promise.reject(new Error('no video is open')),
    singleLayer: () => Promise.resolve(false),
  },
  requestReorderTo: () => undefined,
  confirmReorder: () => undefined,
  dismissReorder: () => undefined,
  requestAdd: () => undefined,
  requestDelete: () => undefined,
  applyPending: () => undefined,
  rejectPending: () => undefined,
  startPreview: () => undefined,
  undo: () => undefined,
  confirmForOutput: () => undefined,
  acknowledgeOutput: () => undefined,
  generateVideo: async () => false,
  retryGeneration: async () => false,
  cancelStills: () => undefined,
  stopVideo: () => undefined,
  sendMessage: () => undefined,
  cancelChat: () => undefined,
};
