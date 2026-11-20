import type { components, paths } from './generated/openapi';

export const API_BASE = '/api/v1';

export function artifactUrl(artifactId: string): string {
  return artifactId.startsWith('data:image/') ? artifactId : `${API_BASE}/artifacts/${encodeURIComponent(artifactId)}`;
}

export type RuntimeStatus =
  paths['/api/v1/runtime']['get']['responses']['200']['content']['application/json'];
export type Problem = components['schemas']['Problem'];
export type ApiErrorCode = components['schemas']['ApiErrorCode'];
export type Job = components['schemas']['Job'];
export type JobState = components['schemas']['JobState'];
export type Project = components['schemas']['Project'];
export type ProjectSummary = components['schemas']['ProjectSummary'];
export type Video = components['schemas']['Video'];
export type VideoView = components['schemas']['VideoView'];
export type CatalogItem = components['schemas']['CatalogItem'];
export type Language = components['schemas']['Language'];
export type PairResponse = components['schemas']['PairResponse'];
export type DraftRequest = components['schemas']['DraftRequest'];

export interface ApiRequest {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  path: string;
  query?: Record<string, string | number | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export interface ApiResponse {
  status: number;
  headers: Record<string, string>;
  body: unknown;
}

export type ApiTransport = (request: ApiRequest) => Promise<ApiResponse>;

/** A server answer that follows the Problem contract (CONTRACTS 3.1). */
export class ApiProblemError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.message_key);
    this.name = 'ApiProblemError';
    this.problem = problem;
  }

  get messageKey(): string {
    return this.problem.message_key;
  }

  get code(): ApiErrorCode {
    return this.problem.code;
  }

  get retryable(): boolean {
    return this.problem.retryable;
  }
}

/** A 409 `revision_conflict` already re-read: the newest video travels with it. */
export class RevisionConflictError extends ApiProblemError {
  readonly current: VideoView;

  constructor(problem: Problem, current: VideoView) {
    super(problem);
    this.name = 'RevisionConflictError';
    this.current = current;
  }

  get currentRevision(): number {
    return this.current.video.revision;
  }
}

/** The request never reached the server. */
export class OfflineError extends Error {
  readonly messageKey = 'error.network';

  constructor(cause?: unknown) {
    super('the request did not reach the server', { cause });
    this.name = 'OfflineError';
  }
}

/** A state-changing request needs the session token the pairing response holds. */
export class SessionMissingError extends Error {
  readonly messageKey = 'error.unauthenticated';

  constructor() {
    super('the session token is missing');
    this.name = 'SessionMissingError';
  }
}

/** A failure outside the Problem contract, for example a proxy error page. */
export class UnexpectedResponseError extends Error {
  readonly messageKey = 'error.unknown';
  readonly status: number;

  constructor(status: number) {
    super(`the server answered ${status} without a problem body`);
    this.name = 'UnexpectedResponseError';
    this.status = status;
  }
}

export function messageKeyOf(error: unknown): string {
  if (error instanceof ApiProblemError) {
    return error.messageKey;
  }
  if (
    error instanceof OfflineError ||
    error instanceof SessionMissingError ||
    error instanceof UnexpectedResponseError
  ) {
    return error.messageKey;
  }
  return 'error.unknown';
}

const fetchTransport: ApiTransport = async (request) => {
  const url = new URL(`${API_BASE}${request.path}`, window.location.origin);
  for (const [name, value] of Object.entries(request.query ?? {})) {
    if (value !== undefined) {
      url.searchParams.set(name, String(value));
    }
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: request.method,
      headers: request.headers,
      body: request.body === undefined ? undefined : JSON.stringify(request.body),
      credentials: 'same-origin',
      signal: request.signal,
    });
  } catch (error) {
    if (request.signal?.aborted === true) {
      throw error;
    }
    throw new OfflineError(error);
  }

  return {
    status: response.status,
    headers: Object.fromEntries(response.headers.entries()),
    body: await readBody(response),
  };
};

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text === '') {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

let transport: ApiTransport = fetchTransport;
// CONTRACTS 13.2: the CSRF token lives in memory for this tab only.
let csrfToken: string | null = null;

export function setTransport(next: ApiTransport): void {
  transport = next;
}

export function resetTransport(): void {
  transport = fetchTransport;
}

export function clearSession(): void {
  csrfToken = null;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

interface RequestOptions {
  idempotencyKey?: string;
  csrf?: boolean;
}

/** One user action gets a fresh key, so a retry of the action is not a new one. */
export function newIdempotencyKey(): string {
  const random =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return random.replace(/[^A-Za-z0-9_-]/gu, '').slice(0, 64);
}

function parseProblem(body: unknown): Problem | null {
  if (typeof body !== 'object' || body === null) {
    return null;
  }
  const record = body as Record<string, unknown>;
  if (typeof record.code !== 'string' || typeof record.message_key !== 'string') {
    return null;
  }
  return body as Problem;
}

function toError(response: ApiResponse): Error {
  const problem = parseProblem(response.body);
  return problem === null ? new UnexpectedResponseError(response.status) : new ApiProblemError(problem);
}

async function request(spec: ApiRequest, options: RequestOptions = {}): Promise<ApiResponse> {
  const headers: Record<string, string> = { Accept: 'application/json', ...spec.headers };
  if (spec.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  if (spec.method !== 'GET' && options.csrf !== false) {
    if (csrfToken === null) {
      throw new SessionMissingError();
    }
    headers['X-CSRF-Token'] = csrfToken;
  }
  if (options.idempotencyKey !== undefined) {
    headers['Idempotency-Key'] = options.idempotencyKey;
  }
  return transport({ ...spec, headers });
}

async function send<T>(spec: ApiRequest, options: RequestOptions = {}): Promise<T> {
  const response = await request(spec, options);
  if (response.status >= 200 && response.status < 300) {
    return response.body as T;
  }
  throw toError(response);
}

interface ListEnvelope<T> {
  items: T[];
  next_cursor: string | null;
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return send<T>({ method: 'GET', path, signal });
}

/**
 * Turns the one-time code from `#pair=` into a session. The token stays in this
 * module; CONTRACTS 13.2 forbids keeping it in persistent browser storage.
 */
export async function pairSession(code: string): Promise<PairResponse> {
  const paired = await send<PairResponse>(
    { method: 'POST', path: '/session/pair', body: { code } },
    { csrf: false },
  );
  csrfToken = paired.csrf_token;
  return paired;
}

/** A reload or a new tab gets a fresh token from the session cookie. */
export async function refreshSession(): Promise<string> {
  const response = await send<{ csrf_token: string }>({ method: 'GET', path: '/session/csrf' });
  csrfToken = response.csrf_token;
  return csrfToken;
}

export async function listFormatCards(signal?: AbortSignal): Promise<CatalogItem[]> {
  const list = await send<ListEnvelope<CatalogItem>>({
    method: 'GET',
    path: '/catalog/format_card',
    query: { limit: 20 },
    signal,
  });
  return list.items;
}

export async function listRecentProjects(signal?: AbortSignal): Promise<ProjectSummary[]> {
  const list = await send<ListEnvelope<ProjectSummary>>({
    method: 'GET',
    path: '/projects',
    query: { limit: 3 },
    signal,
  });
  return list.items;
}

export async function createProject(input: { language: Language }): Promise<Project> {
  return send<Project>(
    { method: 'POST', path: '/projects', body: { title: null, language: input.language } },
    { idempotencyKey: newIdempotencyKey() },
  );
}

export async function createVideo(projectId: string, presetId: string | null = null): Promise<Video> {
  return send<Video>(
    {
      method: 'POST',
      path: `/projects/${encodeURIComponent(projectId)}/videos`,
      body: { from_video_id: null, preset_id: presetId },
    },
    { idempotencyKey: newIdempotencyKey() },
  );
}

export type Preset = components['schemas']['Preset'];

export function createPreset(projectId: string, body: { video_id: string; name: string }): Promise<Preset> {
  return send<Preset>({
    method: 'POST',
    path: `/projects/${encodeURIComponent(projectId)}/presets`,
    body,
  }, { idempotencyKey: newIdempotencyKey() });
}

export function retryJob(jobId: string): Promise<Job> {
  return send<Job>({
    method: 'POST',
    path: `/jobs/${encodeURIComponent(jobId)}/retry`,
  }, { idempotencyKey: newIdempotencyKey() });
}

export async function videoJobs(videoId: string): Promise<Job[]> {
  const items: Job[] = [];
  let cursor: string | null = null;
  do {
    const page: ListEnvelope<Job> = await send({
      method: 'GET',
      path: '/jobs',
      query: { video_id: videoId, limit: 50, cursor: cursor ?? undefined },
    });
    items.push(...page.items.filter((job) => job.video_id === videoId));
    cursor = page.next_cursor;
  } while (cursor !== null);
  return items;
}

export async function submitDraft(videoId: string, body: DraftRequest): Promise<Job> {
  return videoMutation<Job>(videoId, {
    method: 'POST',
    path: `/videos/${encodeURIComponent(videoId)}/draft`,
    body,
  });
}

export async function readVideo(videoId: string, signal?: AbortSignal): Promise<VideoView> {
  return send<VideoView>({ method: 'GET', path: `/videos/${encodeURIComponent(videoId)}`, signal });
}

export async function submitVideoChange(
  videoId: string,
  body: components['schemas']['ChangeRequest'],
  idempotencyKey: string,
): Promise<components['schemas']['ChangePlan']> {
  return send(
    { method: 'POST', path: `/videos/${encodeURIComponent(videoId)}/changes`, body },
    { idempotencyKey },
  );
}

export async function applyVideoChange(changeId: string, baseRevision: number): Promise<Video> {
  return send<Video>({
    method: 'POST',
    path: `/changes/${encodeURIComponent(changeId)}/apply`,
    body: { base_revision: baseRevision },
  }, { idempotencyKey: newIdempotencyKey() });
}

export async function confirmVideoScript(videoId: string, baseRevision: number): Promise<Video> {
  return send<Video>({
    method: 'POST',
    path: `/videos/${encodeURIComponent(videoId)}/script/confirm`,
    body: { base_revision: baseRevision },
  }, { idempotencyKey: newIdempotencyKey() });
}

export interface JobRead {
  notModified: boolean;
  job: Job | null;
  etag: string | null;
}

export async function readJob(
  jobId: string,
  etag: string | null,
  signal?: AbortSignal,
): Promise<JobRead> {
  const headers: Record<string, string> = {};
  if (etag !== null) {
    headers['If-None-Match'] = etag;
  }
  const response = await request({
    method: 'GET',
    path: `/jobs/${encodeURIComponent(jobId)}`,
    headers,
    signal,
  });
  if (response.status === 304) {
    return { notModified: true, job: null, etag };
  }
  if (response.status >= 200 && response.status < 300) {
    return { notModified: false, job: response.body as Job, etag: response.headers.etag ?? null };
  }
  throw toError(response);
}

/** A video mutation that answers a stale revision with the newest video. */
async function videoMutation<T>(videoId: string, spec: ApiRequest): Promise<T> {
  try {
    return await send<T>(spec, { idempotencyKey: newIdempotencyKey() });
  } catch (error) {
    if (error instanceof ApiProblemError && error.code === 'revision_conflict') {
      const current = await readVideo(videoId);
      throw new RevisionConflictError(error.problem, current);
    }
    throw error;
  }
}
