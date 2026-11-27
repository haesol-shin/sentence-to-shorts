import { API_BASE, createProject, createVideo, getCsrfToken, newIdempotencyKey } from '@/shared/api/client';
import type { components } from '@/shared/api/generated/openapi';

import { MAX_TEXT_ATTACHMENTS, type Deployment } from './attachments';
import { ConceptApiError, ORIGIN_PATHS, type ConceptApi, type ConceptApplyResult, type ConceptStartInput } from './api';
import type {
  Attachment,
  ConceptCatalog,
  ConceptDocument,
  ConceptJob,
  ConceptResult,
  Origin,
  PinnedRef,
  Plan,
  Settings,
  SetOp,
  StyleManifest,
} from './types';

type Video = components['schemas']['Video'];
type VideoView = components['schemas']['VideoView'];
type ServerJob = components['schemas']['Job'];
type ServerPlan = components['schemas']['ChangePlan'];
type CatalogKind = 'art_style' | 'template' | 'font';

interface CatalogList {
  items: { id: string; revision: string }[];
  next_cursor: string | null;
}

interface Problem {
  code?: string;
  message_key?: string;
}

const NO_TARGET = { scene_id: null, pointer: null } as const;
const POLL_MS = 400;
const MAX_POLLS = 300;
const CROCKFORD = '0123456789abcdefghjkmnpqrstvwxyz';

/** Settings objects that the server changes as one value, never member by member. */
const WHOLE_VALUES = new Set([
  '/format/layout',
  '/visual/art_style',
  '/visual/character',
  '/audio/voice',
  '/audio/bgm',
  '/caption/font_id',
  '/caption/typing_sound',
  '/caption/extra',
  '/extra_instructions',
]);

/** A TypeID the server accepts for a new material: `m_` and a UUIDv7 in base 32. */
export function newMaterialId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let stamp = BigInt(Date.now());
  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = Number(stamp & 0xffn);
    stamp >>= 8n;
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x70;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  let value = 0n;
  for (const byte of bytes) {
    value = (value << 8n) | BigInt(byte);
  }
  let text = '';
  for (let index = 0; index < 26; index += 1) {
    text = CROCKFORD[Number(value & 31n)] + text;
    value >>= 5n;
  }
  return `m_${text}`;
}

function conceptCode(code: string | undefined): string {
  if (code === 'stale_revision') return 'revision_conflict';
  return code ?? 'internal';
}

async function call<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method === 'POST') {
    const token = getCsrfToken();
    if (token === null) {
      throw new ConceptApiError('unauthenticated', 401, 'the session token is missing');
    }
    if (!(body instanceof FormData)) headers['Content-Type'] = 'application/json';
    headers['X-CSRF-Token'] = token;
    headers['Idempotency-Key'] = newIdempotencyKey();
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
      credentials: 'same-origin',
    });
  } catch (error) {
    throw new ConceptApiError('offline', 0, String(error));
  }
  const text = await response.text();
  let payload: unknown = null;
  if (text !== '') {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (response.status < 200 || response.status >= 300) {
    const problem = (payload ?? {}) as Problem;
    throw new ConceptApiError(conceptCode(problem.code), response.status, problem.message_key ?? '');
  }
  return payload as T;
}

function encode(id: string): string {
  return encodeURIComponent(id);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : [];
}

function localized(language: 'ko' | 'en', ko: string, en: string): string {
  return language === 'ko' ? ko : en;
}

/** The most specific stored origin that covers `path`, as the server resolves it. */
function coveringOrigin(origins: Record<string, Origin>, path: string): Origin {
  let found: Origin = 'default';
  let length = -1;
  for (const [key, origin] of Object.entries(origins)) {
    if ((path === key || path.startsWith(`${key}/`)) && key.length > length) {
      found = origin;
      length = key.length;
    }
  }
  return found;
}

function toSettings(settings: Settings): Settings {
  const origins: Record<string, Origin> = { ...settings.origins };
  for (const path of ORIGIN_PATHS) {
    origins[path] = coveringOrigin(settings.origins, path);
  }
  return { ...settings, origins };
}

function toDocument(video: Video): ConceptDocument {
  return {
    id: video.id,
    projectId: video.project_id,
    revision: video.revision,
    topic: video.topic,
    confirmed: video.stage !== 'draft',
    settings: toSettings(video.settings),
    attachments: toAttachments(video),
  };
}

function toAttachments(video: Video): Attachment[] {
  return video.material.map((material) => ({
    id: material.id,
    kind: 'text',
    name: material.text.slice(0, 24),
    text: material.text,
    state: 'ready',
  }));
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** One set op for each settings value the user changed, with the origin the screen holds. */
function settingsOps(server: Settings, local: Settings): SetOp[] {
  const ops: SetOp[] = [];
  const walk = (prefix: string, before: unknown, after: unknown): void => {
    if (isRecord(before) && isRecord(after) && !WHOLE_VALUES.has(prefix)) {
      for (const key of Object.keys(after)) {
        if (prefix === '' && key === 'origins') continue;
        walk(`${prefix}/${key}`, before[key], after[key]);
      }
      return;
    }
    if (sameValue(before, after)) return;
    const origin = local.origins[prefix] ?? coveringOrigin(local.origins, prefix);
    ops.push({
      op: 'set',
      path: `/settings${prefix}`,
      value: after,
      origin: origin === 'default' ? 'user' : origin,
    });
  };
  walk('', server, local);
  return ops;
}

function toPlan(plan: ServerPlan): Plan {
  const ops = plan.ops.flatMap((op) =>
    op.op === 'set' && op.path.startsWith('/settings/')
      ? [{ ...op, path: op.path.slice('/settings'.length) }]
      : [],
  );
  return { ...plan, ops };
}

function toKind(kind: ServerJob['kind']): ConceptJob['kind'] {
  return kind === 'style' || kind === 'reference' || kind === 'bgm_upload' ? kind : 'chat';
}

function toState(state: ServerJob['state']): ConceptJob['state'] {
  if (state === 'queued' || state === 'running' || state === 'succeeded') return state;
  return state === 'cancelling' ? 'running' : 'failed';
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

interface Composite {
  videoId: string;
  parts: string[];
  notes: string[];
}

/**
 * The concept screen over the running server. Settings travel as direct change
 * plans against the newest revision, a text material is added to the ones the
 * video already holds, and a reference or a message is a job the store polls.
 */
export class HttpConceptApi implements ConceptApi {
  private readonly composites = new Map<string, Composite>();
  private sequence = 0;

  async deployment(): Promise<Deployment> {
    const runtime = await call<{ deployment: Deployment }>('GET', '/runtime');
    return runtime.deployment;
  }

  async catalog(): Promise<ConceptCatalog> {
    const [styles, layouts, fonts] = await Promise.all([
      this.list('art_style'),
      this.list('template'),
      this.list('font'),
    ]);
    return {
      styles: await Promise.all(
        styles.map(async (ref) => ({
          ref,
          manifest: await call<StyleManifest>('GET', `/catalog/art_style/${encode(ref.id)}`),
        })),
      ),
      layouts: await Promise.all(
        layouts.map(async (ref) => {
          const manifest = await call<{ dialog_box?: boolean }>('GET', `/catalog/template/${encode(ref.id)}`);
          return { ref, dialogBox: manifest.dialog_box === true };
        }),
      ),
      fonts,
    };
  }

  async create(input: ConceptStartInput): Promise<ConceptDocument> {
    let video: Video;
    if (input.videoId === undefined) {
      const project = await createProject({ language: input.language ?? 'ko' });
      video = await createVideo(project.id);
    } else {
      video = await this.head(input.videoId);
    }
    const ops: unknown[] = [];
    if (input.videoId === undefined) {
      ops.push({ op: 'set', path: '/topic', value: input.topic, origin: 'user' });
    }
    if (input.duration !== undefined && input.duration !== video.settings.target_duration_s) {
      ops.push({ op: 'set', path: '/settings/target_duration_s', value: input.duration, origin: 'user' });
    }
    const texts = (input.attachments ?? []).filter((attachment) => attachment.kind === 'text');
    if (texts.length > 0) {
      ops.push(this.materialOp(video, texts));
    }
    if (ops.length > 0) {
      await this.change(video, ops);
    }
    return toDocument(await this.head(video.id));
  }

  async load(videoId: string): Promise<ConceptDocument> {
    return toDocument(await this.head(videoId));
  }

  async save(videoId: string, settings: Settings): Promise<ConceptDocument> {
    const video = await this.head(videoId);
    const ops = settingsOps(video.settings, settings);
    if (ops.length > 0) {
      await this.change(video, ops);
      return toDocument(await this.head(videoId));
    }
    return toDocument(video);
  }

  async confirm(videoId: string, baseRevision: number): Promise<ConceptDocument> {
    const video = await call<Video>('POST', `/videos/${encode(videoId)}/concept/confirm`, {
      base_revision: baseRevision,
    });
    return toDocument(video);
  }

  async message(videoId: string, text: string, attachments: Attachment[]): Promise<ConceptJob> {
    const texts = attachments.filter((attachment) => attachment.kind === 'text');
    const references = attachments.filter(
      (attachment) => attachment.kind === 'reference' || attachment.kind === 'link',
    );
    const music = attachments.filter((attachment) => attachment.kind === 'bgm');
    const notes: string[] = [];
    let video = await this.head(videoId);
    const language = video.settings.language;

    if (texts.length > 0) {
      const known = new Set(video.material.map((material) => material.text));
      const fresh = texts.filter((attachment) => !known.has(attachment.text ?? ''));
      if (video.material.length + fresh.length > MAX_TEXT_ATTACHMENTS) {
        throw new ConceptApiError('material_limit', 422, 'At most five text materials');
      }
      if (fresh.length > 0) {
        await this.change(video, [this.materialOp(video, fresh)]);
        video = await this.head(videoId);
      }
      notes.push(
        localized(
          language,
          `글 재료 ${texts.length}개를 영상에 더했어요.`,
          `Added ${texts.length} text material${texts.length === 1 ? '' : 's'}.`,
        ),
      );
    }

    const parts: string[] = [];
    for (const attachment of music) {
      parts.push((await this.uploadMusic(video.project_id, attachment)).id);
    }
    for (const attachment of references) {
      const current = await this.head(videoId);
      parts.push((await this.submitSource(current, attachment)).id);
    }
    if (text.trim() !== '') {
      const current = await this.head(videoId);
      const job = await call<ServerJob>('POST', `/videos/${encode(videoId)}/messages`, {
        base_revision: current.revision,
        text,
        target: NO_TARGET,
      });
      parts.push(job.id);
    }

    if (parts.length === 1 && notes.length === 0) {
      return this.readJob(parts[0]);
    }
    this.sequence += 1;
    const id = `local_${this.sequence}`;
    this.composites.set(id, { videoId, parts, notes });
    return this.readComposite(id);
  }

  async submitStyle(videoId: string, prompt: string, attachment?: Attachment): Promise<ConceptJob> {
    let useReference = false;
    if (attachment !== undefined) {
      const source = await this.submitReference(videoId, attachment);
      const done = await this.settle(source.id);
      if (done.state !== 'succeeded') {
        throw new ConceptApiError('internal', 500, 'The reference could not be analyzed');
      }
      useReference = true;
    }
    const video = await this.head(videoId);
    const job = await call<ServerJob>('POST', '/styles', {
      video_id: videoId,
      base_revision: video.revision,
      base_style: video.settings.visual.art_style,
      instruction: prompt,
      use_reference: useReference,
    });
    return this.toJob(job);
  }

  async submitReference(videoId: string, attachment: Attachment): Promise<ConceptJob> {
    if (attachment.kind !== 'reference' && attachment.kind !== 'link') {
      throw new ConceptApiError('validation_failed', 400, 'A reference file or link is required');
    }
    const video = await this.head(videoId);
    return this.toJob(await this.submitSource(video, attachment));
  }

  async getJob(jobId: string): Promise<ConceptJob> {
    return this.composites.has(jobId) ? this.readComposite(jobId) : this.readJob(jobId);
  }

  async applyPlan(videoId: string, planId: string, baseRevision: number): Promise<ConceptApplyResult> {
    await call<Video>('POST', `/changes/${encode(planId)}/apply`, { base_revision: baseRevision });
    const [document, plan] = await Promise.all([this.load(videoId), this.plan(planId)]);
    return { document, plan };
  }

  async rejectPlan(_videoId: string, planId: string): Promise<Plan> {
    return toPlan(await call<ServerPlan>('POST', `/changes/${encode(planId)}/reject`));
  }

  private async head(videoId: string): Promise<Video> {
    return (await call<VideoView>('GET', `/videos/${encode(videoId)}`)).video;
  }

  private async plan(changeId: string): Promise<Plan> {
    return toPlan(await call<ServerPlan>('GET', `/changes/${encode(changeId)}`));
  }

  private async list(kind: CatalogKind): Promise<PinnedRef[]> {
    const refs: PinnedRef[] = [];
    let cursor: string | null = null;
    do {
      const query: string = cursor === null ? '' : `?cursor=${encodeURIComponent(cursor)}`;
      const page: CatalogList = await call<CatalogList>('GET', `/catalog/${kind}${query}`);
      refs.push(...page.items.map((item) => ({ id: item.id, revision: item.revision })));
      cursor = page.next_cursor;
    } while (cursor !== null);
    return refs;
  }

  /** A direct plan against the video as read; one that asks to be confirmed is applied. */
  private async change(video: Video, ops: unknown[]): Promise<void> {
    const plan = await call<ServerPlan>('POST', `/videos/${encode(video.id)}/changes`, {
      base_revision: video.revision,
      source: 'direct',
      target: NO_TARGET,
      ops,
    });
    if (plan.status === 'proposed') {
      await call<Video>('POST', `/changes/${encode(plan.id)}/apply`, { base_revision: video.revision });
    }
  }

  private materialOp(video: Video, added: readonly Attachment[]): unknown {
    return {
      op: 'set',
      path: '/material',
      value: [
        ...video.material,
        ...added.map((attachment) => ({ id: newMaterialId(), text: attachment.text ?? '' })),
      ],
      origin: 'user',
    };
  }

  private submitSource(video: Video, attachment: Attachment): Promise<ServerJob> {
    if (attachment.kind === 'link' && attachment.url !== undefined) {
      return call<ServerJob>('POST', `/videos/${encode(video.id)}/references/link`, {
        base_revision: video.revision,
        url: attachment.url,
      });
    }
    if (attachment.file === undefined) {
      throw new ConceptApiError('validation_failed', 400, 'The reference has no file or link');
    }
    const form = new FormData();
    form.set('base_revision', String(video.revision));
    form.set('file', attachment.file, attachment.file.name);
    return call<ServerJob>('POST', `/videos/${encode(video.id)}/references`, form);
  }

  private uploadMusic(projectId: string, attachment: Attachment): Promise<ServerJob> {
    if (attachment.file === undefined) {
      throw new ConceptApiError('validation_failed', 400, 'The music has no file');
    }
    const form = new FormData();
    form.set('project_id', projectId);
    form.set('file', attachment.file, attachment.file.name);
    return call<ServerJob>('POST', '/bgm/uploads', form);
  }

  private async readJob(jobId: string): Promise<ConceptJob> {
    return this.toJob(await call<ServerJob>('GET', `/jobs/${encode(jobId)}`));
  }

  private async settle(jobId: string): Promise<ConceptJob> {
    for (let poll = 0; poll < MAX_POLLS; poll += 1) {
      const job = await this.readJob(jobId);
      if (job.state === 'succeeded' || job.state === 'failed') return job;
      await sleep(POLL_MS);
    }
    throw new ConceptApiError('internal', 504, 'The job did not end');
  }

  private async toJob(job: ServerJob): Promise<ConceptJob> {
    const base = { id: job.id, kind: toKind(job.kind), state: toState(job.state) };
    if (base.state === 'succeeded') {
      return { ...base, result: await this.toResult(job) };
    }
    if (base.state === 'failed') {
      return { ...base, result: { plan: null, notes: [], unsupported: [job.error === null ? 'error.internal' : `error.${job.error.code}`] } };
    }
    return base;
  }

  private async toResult(job: ServerJob): Promise<ConceptResult> {
    const result = job.result ?? {};
    const changeId = typeof result.change_id === 'string' ? result.change_id : null;
    const video = job.video_id === null ? null : await this.head(job.video_id);
    const plan = changeId === null ? null : await this.plan(changeId);
    return {
      plan,
      notes: plan?.notes ?? strings(result.notes),
      unsupported: plan?.unsupported ?? strings(result.unsupported),
      ...(video === null ? {} : { revision: video.revision, attachments: toAttachments(video) }),
    };
  }

  private async readComposite(id: string): Promise<ConceptJob> {
    const entry = this.composites.get(id);
    if (entry === undefined) {
      throw new ConceptApiError('not_found', 404, 'Unknown job');
    }
    const parts = await Promise.all(entry.parts.map((partId) => this.readJob(partId)));
    const kind = parts[0]?.kind ?? 'chat';
    if (parts.some((part) => part.state === 'queued' || part.state === 'running')) {
      return { id, kind, state: 'running' };
    }
    const results = parts.flatMap((part) => (part.result === undefined ? [] : [part.result]));
    const video = await this.head(entry.videoId);
    const merged: ConceptResult = {
      plan: results.find((result) => result.plan !== null)?.plan ?? null,
      notes: [...entry.notes, ...results.flatMap((result) => result.notes)],
      unsupported: results.flatMap((result) => result.unsupported),
      revision: video.revision,
      attachments: toAttachments(video),
    };
    return {
      id,
      kind,
      state: parts.some((part) => part.state === 'failed') ? 'failed' : 'succeeded',
      result: merged,
    };
  }
}

export function createHttpConceptApi(): HttpConceptApi {
  return new HttpConceptApi();
}
