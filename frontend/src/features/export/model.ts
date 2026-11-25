import type { Job, VideoView } from '@/shared/api/client';

import type { ActivitySpan, Metrics, PrecheckReport } from './api';

export type ActivityKind = ActivitySpan['kind'];

/**
 * Splits workspace time into the spans the server sums. A hidden tab
 * records nothing, so it never counts as the user's own working time; a job in
 * flight is waiting, not working. Each span is sent at most once, because the
 * server adds the spans up without merging overlaps.
 */
export class ActivityTracker {
  private kind: ActivityKind | null = null;
  private since = 0;
  private closed: ActivitySpan[] = [];

  /** Moves to the next kind at `now`; a kind that stays the same changes nothing. */
  update(next: ActivityKind | null, now: number): void {
    if (next === this.kind) return;
    this.close(now);
    this.kind = next;
    this.since = Math.max(this.since, now);
  }

  /** The spans closed so far plus the open one up to `now`, which then starts over. */
  take(now: number): ActivitySpan[] {
    this.close(now);
    this.since = Math.max(this.since, now);
    return this.takeClosed();
  }

  /** Drain completed spans without splitting the live one. */
  takeClosed(): ActivitySpan[] {
    const spans = this.closed;
    this.closed = [];
    return spans;
  }

  private close(now: number): void {
    if (this.kind !== null && now > this.since) {
      this.closed.push({ kind: this.kind, start_ms: this.since, end_ms: now });
    }
  }
}

export function spanMs(spans: readonly ActivitySpan[], kind: ActivityKind): number {
  return spans
    .filter((span) => span.kind === kind)
    .reduce((total, span) => total + Math.max(0, span.end_ms - span.start_ms), 0);
}

export function activityKind(visible: boolean, waiting: boolean): ActivityKind | null {
  if (!visible) return null;
  return waiting ? 'waiting' : 'active';
}

export function inFlight(job: Job): boolean {
  return job.state === 'queued' || job.state === 'running' || job.state === 'cancelling';
}

/** The final mp4 once it is fresh; anything else cannot be played or saved. */
export function finalArtifactId(view: VideoView | null): string | null {
  if (view === null || view.build.final.state !== 'fresh') return null;
  return view.build.final.artifact?.id ?? null;
}

export function srtReady(view: VideoView | null): boolean {
  return view !== null && view.build.srt.state === 'fresh' && view.build.srt.artifact !== null;
}

export function precheckFromJob(job: Job): PrecheckReport | null {
  const report = job.result?.['precheck'];
  if (report === null || typeof report !== 'object') return null;
  const value = report as Partial<PrecheckReport>;
  if (typeof value.opening_promise !== 'string' || typeof value.ending_answer !== 'string') return null;
  return {
    opening_promise: value.opening_promise,
    ending_answer: value.ending_answer,
    claims: Array.isArray(value.claims) ? value.claims : [],
    hypotheticals: Array.isArray(value.hypotheticals) ? value.hypotheticals : [],
  };
}

/**
 * Whether the check found something to look at before making: a statement of
 * fact the user's material does not back. A video made from one sentence has no
 * material, so its statements have nothing to be checked against.
 */
export function precheckFindsProblem(view: VideoView, report: PrecheckReport): boolean {
  const { material } = view.video;
  return material.length > 0 &&
    report.claims.some((claim) => !material.some((entry) => entry.id === claim.material_id));
}

export function sceneNumberOf(view: VideoView | null, sceneId: string): number {
  return view === null ? 0 : view.video.scene_order.indexOf(sceneId) + 1;
}

export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/** Milliseconds as whole minutes and seconds, for example 65000 as 1 and 5. */
export function formatSpan(ms: number): { minutes: number; seconds: number } {
  const whole = Math.round(ms / 1000);
  return { minutes: Math.floor(whole / 60), seconds: whole % 60 };
}

export function formatCost(micro: number): string {
  const dollars = micro / 1_000_000;
  return `$${dollars.toFixed(dollars < 0.01 ? 4 : 2)}`;
}

export function hasTokens(metrics: Metrics | null): metrics is Metrics & { input_tokens: number; output_tokens: number } {
  return metrics !== null && metrics.input_tokens !== null && metrics.output_tokens !== null;
}

function sceneIds(value: unknown): string[] | null {
  if (!Array.isArray(value) || !value.every((id) => typeof id === 'string' && id.length > 0)) return null;
  return value;
}

function rebuiltScenes(job: Job): readonly string[] | null {
  const rebuilt = sceneIds(job.result?.rebuilt_scene_ids);
  if (rebuilt !== null) return rebuilt;
  const stages: unknown = job.result?.stages;
  if (Array.isArray(stages) && stages.length > 0) {
    const scenes: string[] = [];
    for (const stage of stages) {
      if (typeof stage !== 'object' || stage === null) return null;
      const ids = sceneIds((stage as Record<string, unknown>).rebuilt_scene_ids);
      if (ids === null) return null;
      scenes.push(...ids);
    }
    return scenes;
  }
  // Checkpoints record both new and cached outputs. Persisted stage records
  // may also have placeholder empty lists, so only explicit entries count here.
  const recorded = job.stages.flatMap((stage) => stage.rebuilt_scene_ids);
  return recorded.length === 0 ? null : recorded;
}

export interface TokenCounts {
  input: number;
  output: number;
}

export interface JobUsage {
  durationMs: number | null;
  rebuiltCount: number | null;
  tokens: TokenCounts | null;
}

export function jobUsageMetrics(videoId: string, jobs: readonly Job[] | null): JobUsage {
  let durationMs: number | null = null;
  let rebuilt: Set<string> | null = null;
  let input = 0;
  let output = 0;
  let hasUsage = false;
  let completeUsage = true;

  for (const job of jobs ?? []) {
    if (job.video_id !== videoId) continue;
    for (const usage of job.usage) {
      hasUsage = true;
      if (usage.input_tokens === null || usage.output_tokens === null) {
        completeUsage = false;
      } else {
        input += usage.input_tokens;
        output += usage.output_tokens;
      }
    }
    if (job.kind !== 'generate') continue;
    if (job.started_at !== null && job.ended_at !== null) {
      const elapsed = Date.parse(job.ended_at) - Date.parse(job.started_at);
      if (Number.isFinite(elapsed) && elapsed >= 0) durationMs = (durationMs ?? 0) + elapsed;
    }
    const scenes = rebuiltScenes(job);
    if (scenes !== null) {
      rebuilt ??= new Set();
      for (const id of scenes) rebuilt.add(id);
    }
  }
  return {
    durationMs,
    rebuiltCount: rebuilt?.size ?? null,
    tokens: hasUsage && completeUsage ? { input, output } : null,
  };
}
