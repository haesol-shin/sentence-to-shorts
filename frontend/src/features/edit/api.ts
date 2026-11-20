import type { components } from '@/shared/api/generated/openapi';
import { getCsrfToken, newIdempotencyKey, readVideo } from '@/shared/api/client';

import {
  breaksFlow,
  insertScene,
  removeScene,
  type ArtifactStatus,
  type Scene,
  type SceneFieldPatch,
  type Video,
  type VideoBuild,
  type VideoView,
} from './model';

export type ChangePlan = components['schemas']['ChangePlan'];
export type ChangeOp = ChangePlan['ops'][number];
export type ChangeTarget = ChangePlan['target'];
export type CatalogItem = components['schemas']['CatalogItem'];
export type Job = components['schemas']['Job'];
export type JobState = components['schemas']['JobState'];

export interface StyleOptions {
  backgrounds: string[];
  expressions: string[];
}

export interface EditApi {
  load(videoId: string): Promise<VideoView>;
  change(videoId: string, body: {
    base_revision: number;
    source: 'direct' | 'card';
    target: ChangeTarget;
    ops: ChangeOp[];
  }): Promise<ChangePlan>;
  applyChange(changeId: string, baseRevision: number): Promise<Video>;
  rejectChange(changeId: string): Promise<ChangePlan>;
  readChange(changeId: string): Promise<ChangePlan>;
  previewChange(changeId: string): Promise<Job>;
  previewScenes(videoId: string, baseRevision: number, sceneIds: string[]): Promise<Job>;
  confirmScenes(videoId: string, baseRevision: number): Promise<Video>;
  styleOptions(styleId: string, themeId: string): Promise<StyleOptions>;
  undo(videoId: string, baseRevision: number): Promise<Video>;
  sendMessage(videoId: string, body: {
    base_revision: number;
    text: string;
    target: ChangeTarget;
  }): Promise<Job>;
  generate(videoId: string, baseRevision: number): Promise<Job>;
  cancelJob(jobId: string): Promise<Job>;
  readJob(jobId: string): Promise<Job>;
  listCatalog(kind: 'sfx' | 'voice', videoId: string): Promise<CatalogItem[]>;
}

export class EditApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, status: number, message: string) {
    super(message);
    this.name = 'EditApiError';
    this.code = code;
    this.status = status;
  }
}

const API_BASE = '/api/v1';

export const MOCK_STILL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';

export function artifactUrl(artifactId: string): string {
  return artifactId.startsWith('data:image/') ? artifactId : `${API_BASE}/artifacts/${encodeURIComponent(artifactId)}`;
}

interface RequestOptions {
  idempotency?: boolean;
}

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') {
    const token = getCsrfToken();
    if (token === null) {
      throw new EditApiError('unauthenticated', 401, 'the session token is missing');
    }
    headers['Content-Type'] = 'application/json';
    headers['X-CSRF-Token'] = token;
    if (options.idempotency !== false) {
      headers['Idempotency-Key'] = newIdempotencyKey();
    }
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
    });
  } catch (error) {
    throw new EditApiError('offline', 0, String(error));
  }
  const text = await response.text();
  const payload: unknown = text === '' ? null : (() => {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return null;
    }
  })();
  if (response.status < 200 || response.status >= 300) {
    const problem = payload as { code?: string; message_key?: string } | null;
    throw new EditApiError(problem?.code ?? 'internal', response.status, problem?.message_key ?? '');
  }
  return payload as T;
}

class HttpEditApi implements EditApi {
  load(videoId: string): Promise<VideoView> {
    return request<VideoView>('GET', `/videos/${encodeURIComponent(videoId)}`);
  }

  change(
    videoId: string,
    body: { base_revision: number; source: 'direct' | 'card'; target: ChangeTarget; ops: ChangeOp[] },
  ): Promise<ChangePlan> {
    return request<ChangePlan>('POST', `/videos/${encodeURIComponent(videoId)}/changes`, body);
  }

  applyChange(changeId: string, baseRevision: number): Promise<Video> {
    return request<Video>('POST', `/changes/${encodeURIComponent(changeId)}/apply`, {
      base_revision: baseRevision,
    });
  }

  rejectChange(changeId: string): Promise<ChangePlan> {
    return request<ChangePlan>('POST', `/changes/${encodeURIComponent(changeId)}/reject`);
  }

  readChange(changeId: string): Promise<ChangePlan> {
    return request<ChangePlan>('GET', `/changes/${encodeURIComponent(changeId)}`);
  }

  previewChange(changeId: string): Promise<Job> {
    return request<Job>('POST', `/changes/${encodeURIComponent(changeId)}/preview`);
  }

  previewScenes(videoId: string, baseRevision: number, sceneIds: string[]): Promise<Job> {
    return request<Job>('POST', `/videos/${encodeURIComponent(videoId)}/previews`, {
      base_revision: baseRevision,
      scene_ids: sceneIds,
    });
  }

  confirmScenes(videoId: string, baseRevision: number): Promise<Video> {
    return request<Video>('POST', `/videos/${encodeURIComponent(videoId)}/scenes/confirm`, {
      base_revision: baseRevision,
    });
  }

  async styleOptions(styleId: string, themeId: string): Promise<StyleOptions> {
    const manifest = await request<{
      rig?: { expressions?: string[] };
      themes?: Array<{ id: string; backgrounds?: string[] }>;
    }>('GET', `/catalog/art_style/${encodeURIComponent(styleId)}`);
    const theme = manifest.themes?.find((entry) => entry.id === themeId) ?? manifest.themes?.[0];
    return {
      backgrounds: theme?.backgrounds ?? [],
      expressions: manifest.rig?.expressions ?? [],
    };
  }

  undo(videoId: string, baseRevision: number): Promise<Video> {
    return request<Video>('POST', `/videos/${encodeURIComponent(videoId)}/undo`, {
      base_revision: baseRevision,
    });
  }

  sendMessage(
    videoId: string,
    body: { base_revision: number; text: string; target: ChangeTarget },
  ): Promise<Job> {
    return request<Job>('POST', `/videos/${encodeURIComponent(videoId)}/messages`, body);
  }

  generate(videoId: string, baseRevision: number): Promise<Job> {
    return request<Job>('POST', `/videos/${encodeURIComponent(videoId)}/generate`, {
      base_revision: baseRevision,
    });
  }

  cancelJob(jobId: string): Promise<Job> {
    return request<Job>('POST', `/jobs/${encodeURIComponent(jobId)}/cancel`);
  }

  readJob(jobId: string): Promise<Job> {
    return request<Job>('GET', `/jobs/${encodeURIComponent(jobId)}`);
  }

  async listCatalog(kind: 'sfx' | 'voice', videoId: string): Promise<CatalogItem[]> {
    const list = await request<{ items: CatalogItem[] }>(
      'GET',
      `/catalog/${kind}?video_id=${encodeURIComponent(videoId)}&limit=50`,
    );
    return list.items;
  }
}

const MOCK_TIME = '2026-11-20T00:00:00Z';
const MOCK_DIGEST = '1'.repeat(64);

function missingArtifact(): ArtifactStatus {
  return { state: 'missing', cache_key: null, artifact: null, error_code: null };
}

function mockArtifact(id: string): ArtifactStatus {
  return {
    state: 'fresh',
    cache_key: MOCK_DIGEST,
    artifact: { id, digest: MOCK_DIGEST, cache_key: MOCK_DIGEST },
    error_code: null,
  };
}

let mockSequence = 0;
function nextId(prefix: 'c' | 'j' | 'a' | 's' | 'l'): string {
  mockSequence += 1;
  return `${prefix}_0mock${String(mockSequence).padStart(22, '0')}`;
}

function buildFor(video: Video): VideoBuild {
  const scenes = Object.fromEntries(
    video.scene_order.map((id) => [
      id,
      { still: missingArtifact(), tts: {}, timing: missingArtifact(), layer: null, clip: missingArtifact() },
    ]),
  );
  return {
    video_id: video.id,
    revision: video.revision,
    scenes,
    mix: missingArtifact(),
    final: missingArtifact(),
    srt: missingArtifact(),
    estimated_ms: 0,
    actual_ms: null,
    attribution: [],
  } as VideoBuild;
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function setAt(document: unknown, path: string, value: unknown): void {
  const parts = path.split('/').slice(1);
  let cursor = document as Record<string, unknown> | unknown[];
  for (const part of parts.slice(0, -1)) {
    if (cursor === null || typeof cursor !== 'object') return;
    cursor = (cursor as Record<string, unknown>)[part] as typeof cursor;
  }
  const last = parts.at(-1);
  if (last === undefined || cursor === null || typeof cursor !== 'object') return;
  (cursor as Record<string, unknown>)[last] = value;
}

function applyOps(video: Video, ops: ChangeOp[]): Video {
  const next = clone(video);
  for (const op of ops) {
    if (op.op === 'set') {
      setAt(next, op.path, op.value);
    } else if (op.op === 'reorder') {
      next.scene_order = [...op.order];
    } else if (op.op === 'add_scene') {
      const inserted = insertScene(next, op.after ?? '', clone(op.scene));
      next.scene_order = inserted.order;
      next.scenes = inserted.video.scenes;
    } else if (op.op === 'remove_scene') {
      const removed = removeScene(next, op.scene_id);
      next.scene_order = removed.order;
      next.scenes = removed.video.scenes;
    } else if (op.op === 'replace_scene') {
      next.scenes[op.scene.id] = clone(op.scene);
    }
  }
  return next;
}

function planFor(
  video: Video,
  ops: ChangeOp[],
  source: 'direct' | 'card',
  target: ChangeTarget,
): ChangePlan {
  const touched = new Set<string>();
  let lines = false;
  let structural = false;
  let reordered = false;
  for (const op of ops) {
    if (op.op === 'set') {
      const sceneId = op.path.split('/')[2];
      if (sceneId !== undefined) touched.add(sceneId);
      if (op.path.includes('/lines')) lines = true;
    } else if (op.op === 'add_scene') {
      structural = true;
      touched.add(op.scene.id);
      lines = true;
    } else if (op.op === 'remove_scene') {
      structural = true;
      touched.add(op.scene_id);
    } else if (op.op === 'reorder') {
      reordered = true;
    }
  }
  const sceneIds = [...touched];
  const reorder = ops.find((op) => op.op === 'reorder');
  const warnings =
    reorder !== undefined && breaksFlow(video, reorder.order)
      ? [{ code: 'story_order_broken' as const, scene_id: null }]
      : [];
  return {
    schema_version: 2,
    id: nextId('c'),
    video_id: video.id,
    base_revision: video.revision,
    created_at: MOCK_TIME,
    source,
    target,
    ops,
    effects: {
      script: false,
      scene_ids_text: lines ? sceneIds : [],
      scene_ids_tts: lines ? sceneIds : [],
      scene_ids_render: sceneIds,
      mix: false,
      assemble: structural || reordered || sceneIds.length > 0,
      locked_keys: [],
      overwrites_user_values: [],
    },
    requires_confirmation: structural,
    confirmation_reasons: structural ? ['rebuild_render'] : [],
    warnings,
    unsupported: [],
    notes: [],
    status: structural ? 'proposed' : 'applied',
    applied_revision: structural ? null : video.revision + 1,
  } as ChangePlan;
}

function jobFor(kind: 'generate' | 'chat' | 'preview', video: Video, state: JobState): Job {
  return {
    id: nextId('j'),
    kind,
    owner_id: 'owner',
    state,
    project_id: video.project_id,
    video_id: video.id,
    base_revision: video.revision,
    request_digest: MOCK_DIGEST,
    idempotency_key: null,
    attempt: 1,
    max_attempts: 3,
    created_at: MOCK_TIME,
    started_at: state === 'queued' ? null : MOCK_TIME,
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

export function stageRecord(
  stage: string,
  state: 'running' | 'done' | 'skipped' | 'failed' | 'cancelled',
  scenes: string[] = [],
): Job['stages'][number] {
  return {
    stage,
    state,
    started_ms: 1,
    ended_ms: state === 'running' ? null : 2,
    cache_hits: 0,
    rebuilt_scene_ids: scenes,
  } as Job['stages'][number];
}

function setProgress(job: Job, stage: string | null, done: number, total: number): void {
  job.progress = { stage: stage as Job['progress']['stage'], done, total, waiting_on: null };
}

class MockEditApi implements EditApi {
  constructor(
    private readonly seedView: VideoView | null = null,
    private readonly loader: ((videoId: string) => Promise<VideoView>) | null = null,
  ) {}

  private views = new Map<string, VideoView>();
  private plans = new Map<string, ChangePlan>();
  private jobs = new Map<string, Job>();
  private polls = new Map<string, number>();
  private history = new Map<string, Video[]>();

  private seed(videoId: string): VideoView {
    const existing = this.views.get(videoId);
    if (existing !== undefined) return existing;
    if (this.seedView !== null) {
      const seeded = clone(this.seedView);
      seeded.video.id = videoId;
      seeded.build.video_id = videoId;
      this.views.set(videoId, seeded);
      return seeded;
    }
    const view = {
      video: {
        schema_version: 2,
        id: videoId,
        project_id: 'p_0mock0000000000000000000',
        owner_id: 'owner',
        revision: 1,
        parent_revision: null,
        created_at: MOCK_TIME,
        created_by: 'create',
        change_id: null,
        stage: 'scenes_confirmed',
        derived_from: null,
        topic: '합성 영상',
        material: [],
        reference: null,
        settings: {
          language: 'ko',
          target_duration_s: 30,
          format: {},
          visual: {},
          audio: {
            voice: { id: 'fixed_wav', revision: MOCK_DIGEST },
            bgm: { enabled: true, mood: 'curious', entry: null, gain_db_x10: 0, ducking: true },
            sfx_enabled: true,
          },
          caption: {},
          motion: {},
          locks: {},
          origins: {},
          extra_instructions: [],
        },
        script: { source: 'llm', raw_text: null, title: null },
        scene_order: ['s_0mock10000000000000000000', 's_0mock20000000000000000000', 's_0mock30000000000000000000'],
        scenes: {
          s_0mock10000000000000000000: {
            id: 's_0mock10000000000000000000',
            beat_id: 'hook',
            beat_label: '훅',
            lines: [{ id: 'l_0mock10000000000000000000', display_text: '첫 줄', speech_text: '첫 줄', speaker: 'narrator', highlight: [] }],
            visual: { background_id: 'bg_village', characters: [{ anchor: 'center', expression_id: 'expr_happy', pose_id: 'pose_idle', motion: 'none' }], elements: [], sfx: [], transition_in: 'cut' },
          },
          s_0mock20000000000000000000: {
            id: 's_0mock20000000000000000000',
            beat_id: 'first',
            beat_label: '첫 번째',
            lines: [{ id: 'l_0mock20000000000000000000', display_text: '둘째 줄', speech_text: '둘째 줄', speaker: 'narrator', highlight: [] }],
            visual: { background_id: 'bg_village', characters: [], elements: [], sfx: [], transition_in: 'cut' },
          },
          s_0mock30000000000000000000: {
            id: 's_0mock30000000000000000000',
            beat_id: 'second',
            beat_label: '두 번째',
            lines: [{ id: 'l_0mock30000000000000000000', display_text: '셋째 줄', speech_text: '셋째 줄', speaker: 'narrator', highlight: [] }],
            visual: { background_id: 'bg_village', characters: [], elements: [], sfx: [], transition_in: 'cut' },
          },
        },
      },
      build: buildFor({ scene_order: ['s_0mock10000000000000000000', 's_0mock20000000000000000000', 's_0mock30000000000000000000'] } as Video),
      open_jobs: [],
      pending_change: null,
    } as unknown as VideoView;
    view.build.video_id = videoId;
    this.fillBuild(view);
    this.views.set(videoId, view);
    return view;
  }

  private fillBuild(view: VideoView): void {
    for (const sceneId of view.video.scene_order) {
      const existing = view.build.scenes[sceneId];
      if (existing === undefined) {
        view.build.scenes[sceneId] = { still: missingArtifact(), tts: {}, timing: missingArtifact(), layer: null, clip: missingArtifact() };
      } else if (existing.still.state === 'fresh') {
        existing.still = { ...existing.still, artifact: { id: MOCK_STILL, digest: MOCK_DIGEST, cache_key: MOCK_DIGEST } };
      }
    }
  }

  async load(videoId: string): Promise<VideoView> {
    const existing = this.views.get(videoId);
    if (existing !== undefined) return clone(existing);
    if (this.loader !== null) {
      const loaded = await this.loader(videoId);
      const view = clone(loaded);
      view.video.id = videoId;
      view.build.video_id = videoId;
      this.fillBuild(view);
      this.views.set(videoId, view);
      return clone(view);
    }
    return clone(this.seed(videoId));
  }

  async change(
    videoId: string,
    body: { base_revision: number; source: 'direct' | 'card'; target: ChangeTarget; ops: ChangeOp[] },
  ): Promise<ChangePlan> {
    const view = this.seed(videoId);
    if (body.base_revision !== view.video.revision) {
      throw new EditApiError('revision_conflict', 409, 'revision_conflict');
    }
    const plan = planFor(view.video, body.ops, body.source, body.target);
    this.plans.set(plan.id, plan);
    if (plan.requires_confirmation) return clone(plan);
    const previous = clone(view.video);
    const next = applyOps(view.video, body.ops);
    next.revision += 1;
    next.parent_revision = previous.revision;
    next.created_by = 'change';
    next.change_id = plan.id;
    this.history.set(videoId, [...(this.history.get(videoId) ?? []), previous]);
    view.video = next;
    view.build = buildFor(next);
    view.build.revision = next.revision;
    this.plans.set(plan.id, { ...plan, status: 'applied', applied_revision: next.revision });
    return clone(this.plans.get(plan.id)!);
  }

  async applyChange(changeId: string, baseRevision: number): Promise<Video> {
    const plan = this.plans.get(changeId);
    if (plan === undefined) throw new EditApiError('not_found', 404, 'change');
    const view = this.seed(plan.video_id);
    if (baseRevision !== view.video.revision) throw new EditApiError('revision_conflict', 409, 'revision_conflict');
    const previous = clone(view.video);
    const next = applyOps(view.video, plan.ops);
    next.revision += 1;
    next.parent_revision = previous.revision;
    next.created_by = 'change';
    next.change_id = plan.id;
    this.history.set(plan.video_id, [...(this.history.get(plan.video_id) ?? []), previous]);
    view.video = next;
    view.build = buildFor(next);
    view.build.revision = next.revision;
    this.plans.set(changeId, { ...plan, status: 'applied', applied_revision: next.revision });
    return clone(next);
  }

  async rejectChange(changeId: string): Promise<ChangePlan> {
    const plan = this.plans.get(changeId);
    if (plan === undefined) throw new EditApiError('not_found', 404, 'change');
    const rejected = { ...plan, status: 'rejected' as const };
    this.plans.set(changeId, rejected);
    return clone(rejected);
  }

  async readChange(changeId: string): Promise<ChangePlan> {
    const plan = this.plans.get(changeId);
    if (plan === undefined) throw new EditApiError('not_found', 404, 'change');
    return clone(plan);
  }

  async previewChange(changeId: string): Promise<Job> {
    const plan = this.plans.get(changeId);
    if (plan === undefined) throw new EditApiError('not_found', 404, 'change');
    const view = this.seed(plan.video_id);
    const job = jobFor('preview', view.video, 'succeeded');
    const stills: Record<string, string> = {};
    for (const sceneId of plan.effects.scene_ids_render) {
      stills[sceneId] = MOCK_STILL;
    }
    job.result = { artifacts: { still: stills }, rebuilt_scene_ids: plan.effects.scene_ids_render };
    this.jobs.set(job.id, job);
    return clone(job);
  }

  async undo(videoId: string, baseRevision: number): Promise<Video> {
    const view = this.seed(videoId);
    if (baseRevision !== view.video.revision) throw new EditApiError('revision_conflict', 409, 'revision_conflict');
    const stack = this.history.get(videoId) ?? [];
    const restored = stack.pop();
    if (restored === undefined) throw new EditApiError('nothing_to_undo', 409, 'nothing_to_undo');
    this.history.set(videoId, stack);
    const next = { ...restored, revision: view.video.revision + 1, created_by: 'undo' as const, change_id: null, parent_revision: view.video.revision };
    view.video = next;
    view.build = buildFor(next);
    return clone(next);
  }

  async sendMessage(
    videoId: string,
    body: { base_revision: number; text: string; target: ChangeTarget },
  ): Promise<Job> {
    const view = this.seed(videoId);
    if (body.base_revision !== view.video.revision) throw new EditApiError('revision_conflict', 409, 'revision_conflict');
    const job = jobFor('chat', view.video, 'running');
    this.jobs.set(job.id, job);
    return clone(job);
  }

  async generate(videoId: string, baseRevision: number): Promise<Job> {
    const view = this.seed(videoId);
    if (baseRevision !== view.video.revision) throw new EditApiError('revision_conflict', 409, 'revision_conflict');
    const job = jobFor('generate', view.video, 'running');
    this.jobs.set(job.id, job);
    return clone(job);
  }

  async cancelJob(jobId: string): Promise<Job> {
    const job = this.jobs.get(jobId);
    if (job === undefined) throw new EditApiError('not_found', 404, 'job');
    const next = { ...job, state: 'cancelled' as const, ended_at: MOCK_TIME };
    this.jobs.set(jobId, next);
    return clone(next);
  }

  async readJob(jobId: string): Promise<Job> {
    const job = this.jobs.get(jobId);
    if (job === undefined) throw new EditApiError('not_found', 404, 'job');
    const count = (this.polls.get(jobId) ?? 0) + 1;
    this.polls.set(jobId, count);
    if (job.state === 'cancelled') return clone(job);
    if (job.kind === 'preview') {
      const view = this.seed(job.video_id ?? '');
      const next = clone(job);
      const ids = (job.result?.['scene_ids'] as string[] | undefined) ?? view.video.scene_order;
      if (count <= 1) {
        next.stages = [stageRecord('layer', 'running')];
      } else if (count <= 3) {
        next.stages = [stageRecord('layer', 'done'), stageRecord('still', 'running', ids.slice(0, count - 1))];
        setProgress(next, 'still', Math.min(count - 1, ids.length), ids.length);
      } else {
        next.state = 'succeeded';
        next.ended_at = MOCK_TIME;
        next.stages = [stageRecord('layer', 'done'), stageRecord('still', 'done', ids)];
        setProgress(next, 'still', ids.length, ids.length);
        next.result = { revision: view.video.revision, scene_ids: ids, artifacts: { still: Object.fromEntries(ids.map((id) => [id, MOCK_STILL])) } };
        for (const id of ids) {
          const current = view.build.scenes[id];
          if (current !== undefined) current.still = mockArtifact(MOCK_STILL);
        }
      }
      this.jobs.set(jobId, next);
      return clone(next);
    }
    if (job.kind === 'generate') {
      const view = this.seed(job.video_id ?? '');
      const ids = view.video.scene_order;
      const next = clone(job);
      if (count <= 3) {
        next.stages = [stageRecord('tts', 'running')];
      } else if (count === 4) {
        next.stages = [stageRecord('tts', 'done'), stageRecord('clip', 'running')];
      } else if (count <= 9) {
        const done = Math.min(count - 4, ids.length);
        next.stages = [stageRecord('tts', 'done'), stageRecord('clip', 'running', ids.slice(0, done))];
        setProgress(next, 'clip', done, ids.length);
      } else if (count <= 10) {
        next.stages = [stageRecord('tts', 'done'), stageRecord('still', 'done', ids), stageRecord('clip', 'done', ids), stageRecord('assemble', 'running')];
        setProgress(next, 'clip', ids.length, ids.length);
      } else {
        next.state = 'succeeded';
        next.ended_at = MOCK_TIME;
        next.stages = [stageRecord('tts', 'done'), stageRecord('still', 'done', ids), stageRecord('clip', 'done', ids), stageRecord('assemble', 'done'), stageRecord('srt', 'done')];
        setProgress(next, 'clip', ids.length, ids.length);
        const finalArtifact = nextId('a');
        next.result = { video_id: view.video.id, revision: view.video.revision, artifact_ids: [], artifacts: { final: finalArtifact }, rebuilt_scene_ids: ids };
        view.build.final = mockArtifact(finalArtifact);
      }
      this.jobs.set(jobId, next);
      return clone(next);
    }
    if (job.kind === 'chat') {
      const next = clone(job);
      if (count >= 2) {
        next.state = 'succeeded';
        next.ended_at = MOCK_TIME;
        next.result = { change_id: null, notes: ['합성 대화 결과'], unsupported: [], status: null, applied_revision: null };
      }
      this.jobs.set(jobId, next);
      return clone(next);
    }
    return clone(job);
  }

  async previewScenes(videoId: string, baseRevision: number, sceneIds: string[]): Promise<Job> {
    const view = this.seed(videoId);
    if (baseRevision !== view.video.revision) throw new EditApiError('revision_conflict', 409, 'revision_conflict');
    const job = jobFor('preview', view.video, 'running');
    job.result = { scene_ids: sceneIds };
    this.jobs.set(job.id, job);
    return clone(job);
  }

  async confirmScenes(videoId: string, baseRevision: number): Promise<Video> {
    const view = this.seed(videoId);
    if (baseRevision !== view.video.revision) throw new EditApiError('revision_conflict', 409, 'revision_conflict');
    const next = { ...view.video, stage: 'scenes_confirmed' as const, revision: view.video.revision + 1 };
    view.video = next;
    return clone(next);
  }

  async styleOptions(styleId: string, themeId: string): Promise<StyleOptions> {
    void styleId;
    void themeId;
    return {
      backgrounds: ['bg_village', 'bg_stars', 'bg_park', 'bg_classroom'],
      expressions: ['expr_happy', 'expr_surprised'],
    };
  }

  async listCatalog(kind: 'sfx' | 'voice', videoId: string): Promise<CatalogItem[]> {
    void videoId;
    if (kind === 'sfx') {
      const names = [
        ['pop', '팝', 'Pop'],
        ['whoosh', '휙', 'Whoosh'],
        ['ding', '딩', 'Ding'],
        ['click', '딸깍', 'Click'],
        ['sparkle', '반짝', 'Sparkle'],
        ['thud', '쿵', 'Thud'],
        ['ta_da', '짜잔', 'Ta-da'],
        ['boing', '보잉', 'Boing'],
        ['swish', '휙휙', 'Swish'],
        ['beep', '삐', 'Beep'],
        ['chime', '차임', 'Chime'],
        ['swoosh', '휘익', 'Swoosh'],
      ] as const;
      return names.map(([id, ko, en]) => ({
        kind: 'sfx' as const,
        id,
        revision: MOCK_DIGEST,
        label: { ko, en },
        origin: 'builtin' as const,
        thumbnail: null,
        compatible: null,
      })) as CatalogItem[];
    }
    return [
      { kind: 'voice', id: 'fixed_wav', revision: MOCK_DIGEST, label: { ko: '기본 목소리', en: 'Default voice' }, origin: 'builtin', thumbnail: null, compatible: null },
    ] as CatalogItem[];
  }
}

export function createMockEditApi(seed?: VideoView): EditApi {
  return new MockEditApi(seed ?? null);
}

export function createEditApi(): EditApi {
  return import.meta.env.VITE_API_MODE === 'mock'
    ? new MockEditApi(null, readVideo)
    : new HttpEditApi();
}

/** A small helper for the scene form tests and for callers that compose ops. */
export function sceneFieldOps(scene: Scene, patch: SceneFieldPatch): ChangeOp[] {
  const path = `/scenes/${scene.id}`;
  if (patch.kind === 'background') {
    return [{ op: 'set', path: `${path}/visual/background_id`, value: patch.value ?? '', origin: 'user' }];
  }
  if (patch.kind === 'expression' || patch.kind === 'position') {
    const character = scene.visual?.characters[0];
    return [{
      op: 'set',
      path: `${path}/visual/characters`,
      value: [{
        anchor: patch.anchor ?? character?.anchor ?? 'center',
        expression_id: patch.expressionId ?? character?.expression_id ?? 'expr_neutral',
        pose_id: character?.pose_id ?? 'pose_idle',
        motion: character?.motion ?? 'none',
      }],
      origin: 'user',
    }];
  }
  if (patch.kind === 'highlight') {
    return [{
      op: 'set',
      path: `${path}/lines`,
      value: scene.lines.map((line) =>
        line.id === patch.lineId ? { ...line, highlight: patch.spans ?? [] } : line,
      ),
      origin: 'user',
    }];
  }
  return [{ op: 'set', path: `${path}/visual/sfx`, value: patch.cues ?? [], origin: 'user' }];
}
