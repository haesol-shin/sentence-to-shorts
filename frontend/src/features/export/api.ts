import {
  API_BASE,
  createPreset,
  getCsrfToken,
  getJson,
  newIdempotencyKey,
  readJob as readJobFromServer,
  readVideo,
  videoJobs,
  type Job,
  type VideoView,
  type Preset,
} from '@/shared/api/client';
import type { components } from '@/shared/api/generated/openapi';
import { editedVideoSettings } from '@/shared/api/mock/video-settings';

export interface PrecheckClaim {
  scene_id: string;
  text: string;
  material_id: string | null;
}

/** `PrecheckReport` of the API schema, which no endpoint response names, so the generated types leave it out. */
export interface PrecheckReport {
  opening_promise: string;
  ending_answer: string;
  claims: PrecheckClaim[];
  hypotheticals: string[];
}

export type Metrics = components['schemas']['Metrics'];
export type ActivitySpan = components['schemas']['ActivitySpan'];
export type { Preset } from '@/shared/api/client';

/** The server accepts at most this many spans in one activity request. */
export const MAX_ACTIVITY_SPANS = 200;

export class ExportApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, status: number) {
    super(code);
    this.name = 'ExportApiError';
    this.code = code;
    this.status = status;
  }
}

export interface ExportApi {
  /** The newest video. `fallback` is the view the edit step last held; only the mock answers with it. */
  loadVideo(videoId: string, fallback: VideoView | null): Promise<VideoView>;
  readJob(jobId: string): Promise<Job>;
  startPrecheck(videoId: string, baseRevision: number): Promise<Job>;
  jobs(videoId: string): Promise<Job[]>;
  metrics(videoId: string): Promise<Metrics>;
  recordActivity(videoId: string, spans: readonly ActivitySpan[]): Promise<void>;
  savePreset(projectId: string, body: { video_id: string; name: string }): Promise<Preset>;
}

/** The attachment links the player, the mp4 button and the caption button share. */
export function downloadUrl(videoId: string, kind: 'mp4' | 'srt'): string {
  return `${API_BASE}/videos/${encodeURIComponent(videoId)}/download/${kind}`;
}

function parseBody(text: string): unknown {
  if (text === '') return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

async function post<T>(path: string, body: unknown, keepalive = false): Promise<T> {
  const token = getCsrfToken();
  if (token === null) throw new ExportApiError('unauthenticated', 401);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-CSRF-Token': token,
        'Idempotency-Key': newIdempotencyKey(),
      },
      body: JSON.stringify(body),
      credentials: 'same-origin',
      keepalive,
    });
  } catch {
    throw new ExportApiError('offline', 0);
  }
  const text = await response.text();
  const payload = parseBody(text);
  if (response.status < 200 || response.status >= 300) {
    const problem = payload as { code?: string } | null;
    throw new ExportApiError(problem?.code ?? 'internal', response.status);
  }
  return payload as T;
}

class HttpExportApi implements ExportApi {
  loadVideo(videoId: string): Promise<VideoView> {
    return readVideo(videoId);
  }

  async readJob(jobId: string): Promise<Job> {
    const read = await readJobFromServer(jobId, null);
    if (read.job === null) throw new ExportApiError('internal', 200);
    return read.job;
  }

  startPrecheck(videoId: string, baseRevision: number): Promise<Job> {
    return post<Job>(`/videos/${encodeURIComponent(videoId)}/precheck`, { base_revision: baseRevision });
  }

  jobs(videoId: string): Promise<Job[]> {
    return videoJobs(videoId);
  }

  metrics(videoId: string): Promise<Metrics> {
    return getJson<Metrics>(`/videos/${encodeURIComponent(videoId)}/metrics`);
  }

  async recordActivity(videoId: string, spans: readonly ActivitySpan[]): Promise<void> {
    await post<null>(`/videos/${encodeURIComponent(videoId)}/activity`, { spans }, true);
  }

  savePreset(projectId: string, body: { video_id: string; name: string }): Promise<Preset> {
    return createPreset(projectId, body);
  }
}

const MOCK_TIME = '2026-11-20T00:00:00Z';
const MOCK_DIGEST = '1'.repeat(64);

let mockSequence = 0;

function mockPrecheckJob(view: VideoView): Job {
  mockSequence += 1;
  return {
    id: `j_0mockexport${String(mockSequence).padStart(13, '0')}`,
    kind: 'precheck',
    owner_id: 'owner',
    state: 'running',
    project_id: view.video.project_id,
    video_id: view.video.id,
    base_revision: view.video.revision,
    request_digest: MOCK_DIGEST,
    idempotency_key: null,
    attempt: 1,
    max_attempts: 3,
    created_at: MOCK_TIME,
    started_at: MOCK_TIME,
    ended_at: null,
    deadline_at: null,
    progress: { stage: null, done: 0, total: 0, waiting_on: null },
    stages: [],
    checkpoints: [],
    usage: [],
    result: null,
    error: null,
    partial: false,
  } as Job;
}

/**
 * Answers in memory for a run without a server. The recorded fixtures carry no
 * precheck result and no usage figures, so this keeps synthetic ones.
 */
class MockExportApi implements ExportApi {
  private view: VideoView | null = null;
  private readonly prechecks = new Map<string, Job>();
  private readonly polls = new Map<string, number>();
  private readonly spans = new Map<string, ActivitySpan[]>();

  async loadVideo(videoId: string, fallback: VideoView | null): Promise<VideoView> {
    const view = structuredClone(fallback?.video.id === videoId ? fallback : await readVideo(videoId));
    editedVideoSettings.set(videoId, view.video.settings);
    // The mock edit step builds the mp4 but not the caption file the server also makes.
    if (view.build.final.state === 'fresh' && view.build.srt.state !== 'fresh') {
      view.build.srt = {
        state: 'fresh',
        cache_key: MOCK_DIGEST,
        artifact: { id: 'a_0mocksrt000000000000000000', digest: MOCK_DIGEST, cache_key: MOCK_DIGEST },
        error_code: null,
      };
    }
    this.view = structuredClone(view);
    return view;
  }

  async readJob(jobId: string): Promise<Job> {
    const job = this.prechecks.get(jobId);
    if (job === undefined) throw new ExportApiError('not_found', 404);
    const count = (this.polls.get(jobId) ?? 0) + 1;
    this.polls.set(jobId, count);
    if (count < 2 || this.view === null || this.view.video.id !== job.video_id) return structuredClone(job);
    const next = structuredClone(job);
    next.state = 'succeeded';
    next.ended_at = MOCK_TIME;
    const { video } = this.view;
    const ids = video.scene_order;
    const first = video.scenes[ids[0] ?? '']?.lines[0]?.display_text ?? '';
    next.result = {
      precheck: {
        opening_promise: first === '' ? '첫 장면에서 영상이 알려 줄 것을 말해요.' : first,
        ending_answer: '마지막 장면에서 처음의 질문에 답해요.',
        claims: ids.slice(0, 2).map((id) => ({
          scene_id: id,
          text: video.scenes[id]?.lines[0]?.display_text ?? '',
          material_id: video.material[0]?.id ?? null,
        })),
        hypotheticals: ids.slice(-1),
      } satisfies PrecheckReport,
    };
    this.prechecks.set(jobId, next);
    return structuredClone(next);
  }

  async startPrecheck(videoId: string, baseRevision: number): Promise<Job> {
    const view = await this.current(videoId, baseRevision);
    const job = mockPrecheckJob(view);
    this.prechecks.set(job.id, job);
    return structuredClone(job);
  }

  jobs(): Promise<Job[]> {
    // Live generation is owned by the edit API in mock mode, too.
    return Promise.resolve([]);
  }

  async metrics(videoId: string): Promise<Metrics> {
    const total = (kind: ActivitySpan['kind']) =>
      (this.spans.get(videoId) ?? [])
        .filter((span) => span.kind === kind)
        .reduce((sum, span) => sum + Math.max(0, span.end_ms - span.start_ms), 0);
    return {
      active_ms: total('active'),
      waiting_ms: total('waiting'),
      job_wall_ms: 0,
      input_tokens: 1240,
      output_tokens: 680,
      cost_micro_usd: null,
      regenerated_scene_ids: [],
    };
  }

  async recordActivity(videoId: string, spans: readonly ActivitySpan[]): Promise<void> {
    const recorded = this.spans.get(videoId);
    if (recorded === undefined) this.spans.set(videoId, [...spans]);
    else recorded.push(...spans);
  }

  async savePreset(projectId: string, body: { video_id: string; name: string }): Promise<Preset> {
    return createPreset(projectId, body);
  }

  private async current(videoId: string, baseRevision: number): Promise<VideoView> {
    const view = this.view?.video.id === videoId ? this.view : await this.loadVideo(videoId, null);
    if (view.video.revision !== baseRevision) throw new ExportApiError('revision_conflict', 409);
    return view;
  }
}

export function createExportApi(): ExportApi {
  return import.meta.env.VITE_API_MODE === 'mock' ? new MockExportApi() : new HttpExportApi();
}
