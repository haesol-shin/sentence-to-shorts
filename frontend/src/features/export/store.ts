import { useLayoutEffect, useSyncExternalStore } from 'react';

import type { Job, VideoView } from '@/shared/api/client';
import { pollDelay } from '@/shared/lib/use-job';

import { createExportApi, type ExportApi, type Metrics, type PrecheckReport, type Preset } from './api';
import { finalArtifactId, inFlight, precheckFromJob } from './model';

/**
 * What the export step can be showing:
 * `empty` has no video, `loading` and `failed` belong to reading it, `idle`
 * is a video not yet made, `making` is a generate job in flight and `ready`
 * has the final mp4.
 */
export type ExportPhase = 'empty' | 'loading' | 'failed' | 'idle' | 'making' | 'incomplete' | 'ready';

export type PrecheckStatus = 'idle' | 'running' | 'done' | 'failed';

export interface ExportState {
  videoId: string | null;
  phase: ExportPhase;
  view: VideoView | null;
  precheck: { status: PrecheckStatus; report: PrecheckReport | null };
  metrics: Metrics | null;
  history: readonly Job[] | null;
  stopped: Job | null;
  /** The result card pops up once per finished video, never on a plain visit. */
  cardOpen: boolean;
  preset: 'idle' | 'saving' | 'saved' | 'failed';
}

function initial(): ExportState {
  return {
    videoId: null,
    phase: 'empty',
    view: null,
    precheck: { status: 'idle', report: null },
    metrics: null,
    history: null,
    stopped: null,
    cardOpen: false,
    preset: 'idle',
  };
}

let api: ExportApi = createExportApi();
let state: ExportState = initial();
let epoch = 0;
const listeners = new Set<() => void>();
const timers = new Set<number>();
/** A finished check stays for its revision, so going back and forth never asks the model again. */
const reports = new Map<string, PrecheckReport>();

function reportKey(view: VideoView): string {
  return `${view.video.id}@${view.video.revision}`;
}

function patch(next: Partial<ExportState>): void {
  state = { ...state, ...next };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function clearTimers(): void {
  for (const timer of timers) window.clearTimeout(timer);
  timers.clear();
}

/** The one API the screen, its top bar seat and the activity reports share. */
export function exportApi(): ExportApi {
  return api;
}

/** Swaps the API and forgets the session. Tests and the mock run use it. */
export function configureExport(next: ExportApi | null): void {
  epoch += 1;
  clearTimers();
  reports.clear();
  api = next ?? createExportApi();
  state = initial();
  for (const listener of listeners) listener();
}

export function useExportState(): ExportState {
  return useSyncExternalStore(subscribe, () => state);
}

const SEEN_KEY = 's2s.export.cardSeen.';

function cardSeen(videoId: string): string | null {
  try {
    return window.sessionStorage.getItem(`${SEEN_KEY}${videoId}`);
  } catch {
    return null;
  }
}

function markCardSeen(videoId: string, artifactId: string): void {
  try {
    window.sessionStorage.setItem(`${SEEN_KEY}${videoId}`, artifactId);
  } catch {
    // A browser that blocks storage shows the card again on the next visit.
  }
}

/** Reads a job until it ends, one read now and then one per poll delay. */
function follow(jobId: string, mine: number, done: (job: Job | null) => void): void {
  const stale = () => epoch !== mine;
  const read = async () => {
    try {
      const job = await api.readJob(jobId);
      if (stale()) return;
      if (inFlight(job)) schedule();
      else done(job);
    } catch {
      if (!stale()) done(null);
    }
  };
  const schedule = () => {
    const timer = window.setTimeout(() => {
      timers.delete(timer);
      void read();
    }, pollDelay(document.visibilityState));
    timers.add(timer);
  };
  void read();
}

async function loadMetrics(videoId: string, mine: number): Promise<void> {
  try {
    const metrics = await api.metrics(videoId);
    if (epoch === mine) patch({ metrics });
  } catch {
    if (epoch === mine) patch({ metrics: null });
  }
}

function runPrecheckFor(view: VideoView, mine: number): void {
  patch({ precheck: { status: 'running', report: null } });
  const failed = () => {
    if (epoch === mine) patch({ precheck: { status: 'failed', report: null } });
  };
  api
    .startPrecheck(view.video.id, view.video.revision)
    .then((job) => {
      if (epoch !== mine) return;
      follow(job.id, mine, (finished) => {
        const report = finished?.state === 'succeeded' ? precheckFromJob(finished) : null;
        if (report === null) failed();
        else {
          reports.set(reportKey(view), report);
          patch({ precheck: { status: 'done', report } });
        }
      });
    })
    .catch(failed);
}

async function settle(view: VideoView, mine: number, observed: Job | null): Promise<void> {
  const videoId = view.video.id;
  const history = await api.jobs(videoId).catch(() => null);
  if (epoch !== mine) return;
  const latest = history?.find((job) => job.kind === 'generate' && (
    inFlight(job) || view.open_jobs.includes(job.id) || job.base_revision === view.video.revision
  ));
  const generation = latest !== undefined && inFlight(latest) && (
    latest.id !== observed?.id || latest.attempt > (observed?.attempt ?? 0)
  ) ? latest : observed ?? latest ?? null;
  const active = generation !== null && inFlight(generation) ? generation : null;
  if (active !== null) {
    patch({ view, phase: 'making' });
    follow(active.id, mine, (job) => {
      if (job === null) patch({ phase: 'failed' });
      else void load(videoId, null, mine, job);
    });
    return;
  }
  if (history === null && generation === null && view.open_jobs.length > 0) {
    patch({ phase: 'failed' });
    return;
  }
  if (latest !== undefined && !inFlight(latest) && view.open_jobs.includes(latest.id)) {
    // The job ended between reading the video and the job list. The first
    // snapshot may contain the MP4 but not the captions written after it.
    if (observed === null) void load(videoId, null, mine, latest);
    else patch({ phase: 'failed' });
    return;
  }
  if (generation !== null && (generation.state === 'failed' || generation.state === 'cancelled')) {
    patch({ view, phase: 'incomplete', stopped: generation });
    return;
  }
  const artifactId = finalArtifactId(view);
  if (artifactId !== null) {
    const open = state.cardOpen || cardSeen(videoId) !== artifactId;
    if (open) markCardSeen(videoId, artifactId);
    const runs = generation !== null && !history?.some((job) => job.id === generation.id)
      ? [generation, ...(history ?? [])]
      : history;
    patch({ view, phase: 'ready', cardOpen: open, history: runs, stopped: null });
    void loadMetrics(videoId, mine);
    return;
  }
  const cached = reports.get(reportKey(view));
  patch({ view, phase: 'idle', stopped: null, precheck: { status: cached === undefined ? 'idle' : 'done', report: cached ?? null } });
  if (cached === undefined && view.video.stage === 'scenes_confirmed') runPrecheckFor(view, mine);
}

async function load(videoId: string, seed: VideoView | null, mine: number, observed: Job | null): Promise<void> {
  try {
    const view = await api.loadVideo(videoId, seed);
    if (epoch !== mine) return;
    if (view.video.id !== videoId) {
      patch({ phase: 'failed' });
      return;
    }
    await settle(view, mine, observed);
  } catch {
    if (epoch === mine) patch({ phase: 'failed' });
  }
}

/**
 * Follows the active workspace video, never a previous edit snapshot. The
 * edit provider owns jobs it knows about and refreshes its view on success.
 */
export function useExportSession(
  videoId: string | null, seed: VideoView | null, job: Job | null = null,
  waitingForResult = false, loadingWorkspace = false,
): void {
  useLayoutEffect(() => {
    const mine = ++epoch;
    clearTimers();
    const previous = state;
    const same = previous.videoId === videoId;
    const video = seed?.video.id === videoId ? seed : null;
    state = initial();
    patch({
      videoId,
      phase: videoId === null ? 'empty' : waitingForResult ? 'making' : 'loading',
      view: waitingForResult ? video : null,
      cardOpen: same && previous.cardOpen,
      preset: same && previous.preset !== 'saving' ? previous.preset : 'idle',
    });
    if (videoId !== null && !waitingForResult && !loadingWorkspace) void load(videoId, video, mine, job);
    return () => {
      if (epoch === mine) epoch += 1;
      clearTimers();
    };
  }, [videoId, seed, job, waitingForResult, loadingWorkspace]);
}

export function reloadExport(): void {
  const videoId = state.videoId;
  if (videoId === null) return;
  patch({ phase: 'loading' });
  void load(videoId, state.view, epoch, null);
}

export function retryPrecheck(): void {
  if (state.view !== null && state.precheck.status !== 'running') runPrecheckFor(state.view, epoch);
}

export function closeCard(): void {
  patch({ cardOpen: false });
}

/** The explicit save for the next video; nothing is saved without this call. */
export function saveForNextVideo(name: string, onSaved: (preset: Preset) => void): void {
  const view = state.view;
  if (view === null || state.preset === 'saving') return;
  const mine = epoch;
  patch({ preset: 'saving' });
  api
    .savePreset(view.video.project_id, { video_id: view.video.id, name })
    .then((preset) => {
      if (epoch !== mine) return;
      onSaved(preset);
      patch({ preset: 'saved' });
    })
    .catch(() => {
      if (epoch === mine) patch({ preset: 'failed' });
    });
}

export function refreshMetrics(videoId = state.videoId): void {
  if (videoId !== null && state.videoId === videoId && state.phase === 'ready') void loadMetrics(videoId, epoch);
}
