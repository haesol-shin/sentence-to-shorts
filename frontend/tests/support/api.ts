import { vi } from 'vitest';

import { resetTransport } from '@/shared/api/client';
import { resetSession } from '@/shared/lib/session';

export interface RecordedCall {
  method: string;
  path: string;
  query: string;
  headers: Record<string, string>;
  body: unknown;
}

export interface Answer {
  status: number;
  body?: unknown;
  headers?: Record<string, string>;
}

export type RouteHandler = (call: RecordedCall) => Answer | Promise<Answer>;

export interface ApiStub {
  calls: RecordedCall[];
  count(method: string, path: string): number;
}

function toResponse(answer: Answer): Response {
  const headers = new Map(
    Object.entries({ 'content-type': 'application/json', ...answer.headers }).map(([name, value]) => [
      name.toLowerCase(),
      value,
    ]),
  );
  return {
    status: answer.status,
    headers: { entries: () => headers.entries() },
    text: async () => (answer.body === undefined ? '' : JSON.stringify(answer.body)),
  } as unknown as Response;
}

/**
 * Replaces `fetch` with a table of recorded answers, keyed as
 * `"<METHOD> /api/v1/<path>"`, and records every call the client makes.
 */
export function stubApi(routes: Record<string, RouteHandler>): ApiStub {
  const calls: RecordedCall[] = [];

  const fetchLike = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input), 'http://127.0.0.1:4173');
    const method = (init?.method ?? 'GET').toUpperCase();
    const headers = new Headers(init?.headers);
    const call: RecordedCall = {
      method,
      path: url.pathname,
      query: url.search,
      headers: Object.fromEntries(headers.entries()),
      body: typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : null,
    };
    calls.push(call);

    const handler = routes[`${method} ${url.pathname}`];
    return toResponse(handler === undefined ? { status: 404 } : await handler(call));
  };

  vi.stubGlobal('fetch', fetchLike);
  resetTransport();
  resetSession();

  return {
    calls,
    count: (method, path) =>
      calls.filter((call) => call.method === method && call.path === path).length,
  };
}

export const DRAFT_JOB = 'j_08c71zekrt8ceaqnmy5jjy5zvn';
export const DRAFT_JOB_PATH = `/api/v1/jobs/${DRAFT_JOB}`;
export const DRAFT_VIDEO = 'v_0hzb7bexv28termtt2ypc6trzt';
export const DRAFT_VIDEO_PATH = `/api/v1/videos/${DRAFT_VIDEO}`;

export const draftJob = {
  id: DRAFT_JOB,
  kind: 'draft',
  state: 'queued',
  progress: { stage: null, done: 0, total: 0, waiting_on: null },
};

/** A draft job answer in `state`; a done job carries the result it applied. */
export function draftAnswer(state: string, status: 'applied' | 'proposed' = 'applied') {
  return {
    ...draftJob,
    state,
    ...(state === 'succeeded' ? { result: { status } } : {}),
  };
}

export const draftVideo = {
  id: DRAFT_VIDEO,
  project_id: 'p_06pxfteaw88hs93kkckw5j51ng',
  revision: 1,
  stage: 'draft',
};

const CARD_LABELS: Record<string, { ko: string; en: string }> = {
  just_three: { ko: '딱 3가지만', en: 'Just 3 Things' },
  its_like: { ko: '○○로 치면', en: "It's Like" },
  what_if: { ko: '만약 ~라면?', en: 'What If?' },
};

/** The smallest session a screen needs: tokens, cards, one project and a draft. */
export function shellRoutes(): Record<string, RouteHandler> {
  return {
    'GET /api/v1/session/csrf': () => ({ status: 200, body: { csrf_token: 'c'.repeat(40) } }),
    'POST /api/v1/session/pair': () => ({
      status: 200,
      body: {
        csrf_token: 'c'.repeat(40),
        profile: 'fixture',
        deployment: 'local',
        ui_language: 'ko',
      },
    }),
    'GET /api/v1/runtime': () => ({
      status: 200,
      body: {
        app_version: '0.1.0',
        profile: 'fixture',
        deployment: 'local',
        brand: { display_name_ko: '테스트 앱', display_name_en: 'Test app' },
        items: [],
        prepare: {
          groups: [
            { id: 'voice', state: 'ready', done: 100, total: 100, error_code: null, retry_at: null },
            { id: 'transcribe', state: 'ready', done: 50, total: 50, error_code: null, retry_at: null },
            { id: 'align_en', state: 'ready', done: 20, total: 20, error_code: null, retry_at: null },
          ],
        },
        llm_auth: { adapter: 'fixture', state: 'ok' },
        capabilities: {
          open_edit_play: true,
          render: false,
          tts: true,
          llm: true,
          link_download: false,
        },
      },
    }),
    'GET /api/v1/catalog/format_card': () => ({
      status: 200,
      body: {
        items: Object.entries(CARD_LABELS).map(([id, label]) => ({
          kind: 'format_card',
          id,
          revision: '0'.repeat(64),
          label,
          origin: 'builtin',
          thumbnail: null,
          compatible: null,
        })),
        next_cursor: null,
      },
    }),
    'GET /api/v1/projects': () => ({
      status: 200,
      body: {
        items: [
          { id: 'p_06pxfteaw88hs93kkckw5j51ng', title: '커피 시리즈', updated_at: '2026-11-14T12:00:00Z', video_count: 3 },
        ],
        next_cursor: null,
      },
    }),
    'POST /api/v1/projects': () => ({
      status: 201,
      body: { id: 'p_06pxfteaw88hs93kkckw5j51ng', title: '', revision: 1 },
    }),
    'POST /api/v1/projects/p_06pxfteaw88hs93kkckw5j51ng/videos': () => ({
      status: 201,
      body: draftVideo,
    }),
    [`POST ${DRAFT_VIDEO_PATH}/draft`]: () => ({ status: 202, body: draftJob }),
    [`GET ${DRAFT_JOB_PATH}`]: () => ({ status: 200, body: draftJob }),
    [`GET ${DRAFT_VIDEO_PATH}`]: () => ({
      status: 200,
      body: {
        video: { ...draftVideo, revision: 4 },
        build: null,
        open_jobs: [],
        pending_change: null,
      },
    }),
  };
}
