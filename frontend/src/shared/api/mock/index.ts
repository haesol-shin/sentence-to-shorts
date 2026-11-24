import {
  API_BASE,
  setTransport,
  type ApiRequest,
  type ApiResponse,
  type Job,
  type PrepareGroup,
  type Preset,
  type RuntimeStatus,
  type Video,
  type VideoView,
} from '../client';
import { withMockStory, withMockStoryStills } from './story';
import { editedVideoSettings } from './video-settings';

interface Fixture {
  operationId: string;
  method: string;
  path_template: string;
  response: {
    status: number;
    media_type: string | null;
    body: unknown;
  };
}

// The recorded API answers live in the repository fixtures, outside the
// frontend root, so a mock run speaks the same bodies as the contract tests.
const files = import.meta.glob('../../../../../fixtures/api/*.json', { eager: true }) as Record<
  string,
  { default: Fixture }
>;

const fixtures = Object.values(files).map((module) => module.default);

function templatePattern(template: string): RegExp {
  const source = template
    .split(/(\{[^}]+\})/u)
    .map((part) =>
      part.startsWith('{') ? '[^/]+' : part.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'),
    )
    .join('');
  return new RegExp(`^${source}$`, 'u');
}

const routes = fixtures.map((fixture) => ({
  fixture,
  pattern: templatePattern(fixture.path_template),
}));

/**
 * The recorded answer for a request, or a 404 when no fixture covers it. The
 * transport sees the path without the base, while fixtures record the full one.
 */
export function mockResponse(request: ApiRequest): ApiResponse {
  const path = `${API_BASE}${request.path}`;
  const match = routes.find(
    ({ fixture, pattern }) => fixture.method === request.method && pattern.test(path),
  );
  if (match === undefined) {
    return { status: 404, headers: {}, body: null };
  }
  return { status: match.fixture.response.status, headers: {}, body: match.fixture.response.body };
}

interface QueuedDraft {
  job: Job;
  queuedAt: number;
  revision: number;
}

/** A draft waits in the queue for a moment, then applies, so the queue banner and the finished state both show. */
const DRAFT_QUEUE_MS = 1500;

function settled({ job, queuedAt, revision }: QueuedDraft): Job {
  if (Date.now() - queuedAt < DRAFT_QUEUE_MS) return job;
  return { ...job, state: 'succeeded', result: { status: 'applied', revision } };
}

/**
 * How far the voice models are. The recorded runtime answer is mid-download, so
 * a screen would show a preparing button in every mock run; the default is a
 * ready install, and a run opts in with `?mock_prepare=downloading`, `retrying`
 * or `failed` in the address.
 */
export type MockPrepare = 'ready' | 'downloading' | 'retrying' | 'failed';

const MOCK_PREPARE: readonly MockPrepare[] = ['ready', 'downloading', 'retrying', 'failed'];

function mockPrepareFromAddress(): MockPrepare {
  const asked = new URLSearchParams(window.location.search).get('mock_prepare');
  return MOCK_PREPARE.find((state) => state === asked) ?? 'ready';
}

/**
 * Open the app with `?mock_llm=missing` for the release first run: the runtime
 * answers the release profile with no key, and saving one makes it usable.
 */
function mockLlmMissingFromAddress(): boolean {
  return new URLSearchParams(window.location.search).get('mock_llm') === 'missing';
}

function prepareGroups(recorded: readonly PrepareGroup[], mode: MockPrepare): PrepareGroup[] {
  if (mode === 'downloading') return recorded.map((group) => ({ ...group }));
  return recorded.map((group) => {
    if (mode === 'ready') return { ...group, state: 'ready', done: group.total };
    if (group.id !== 'voice') return { ...group };
    return mode === 'retrying'
      ? { ...group, state: 'retrying', retry_at: new Date(Date.now() + 15_000).toISOString() }
      : { ...group, state: 'failed', error_code: 'download_failed' };
  });
}

/** Uses recorded answers for static resources and isolates each video started in the app. */
export function installMockApi(prepare: MockPrepare = mockPrepareFromAddress()): void {
  const videos = new Map<string, { created: Video; draftMessage: string | null }>();
  const draftJobs = new Map<string, QueuedDraft>();
  const presets = new Map<string, Preset>();
  let sequence = 0;
  editedVideoSettings.clear();
  const nextId = (prefix: string) => `${prefix}_${(++sequence).toString(32).padStart(25, '0')}`;
  let groups: PrepareGroup[] | null = null;
  let llmMissing = mockLlmMissingFromAddress();

  setTransport(async (request) => {
    const fixture = mockResponse(request);
    const [, area, id, resource] = request.path.split('/');
    if (fixture.status >= 400) return fixture;
    if (request.method === 'GET' && area === 'runtime' && id === undefined) {
      const recorded = fixture.body as RuntimeStatus;
      groups ??= prepareGroups(recorded.prepare.groups, prepare);
      const llm: Partial<RuntimeStatus> = llmMissing
        ? { profile: 'release', llm_auth: { adapter: recorded.llm_auth.adapter, state: 'missing' } }
        : {};
      return { ...fixture, body: { ...recorded, ...llm, prepare: { groups } } satisfies RuntimeStatus };
    }
    if (request.method === 'PUT' && area === 'credentials' && id === 'llm') {
      llmMissing = false;
      return fixture;
    }
    if (request.method === 'POST' && area === 'runtime' && id === 'prepare') {
      // A failed group is queued again and moves on as a download.
      groups = groups?.map((group) =>
        group.state === 'failed' ? { ...group, state: 'downloading', error_code: null } : group,
      ) ?? null;
      return fixture;
    }
    if (request.method === 'POST' && area === 'projects' && id !== undefined && resource === 'videos') {
      const { preset_id: presetId } = request.body as { preset_id: string | null };
      const preset = presetId === null ? null : presets.get(presetId);
      if (presetId !== null && preset?.project_id !== id) return { status: 404, headers: {}, body: null };
      const template = fixture.body as Video;
      const created: Video = {
        ...template,
        id: nextId('v'),
        project_id: id,
        created_by: preset === null ? 'create' : 'next_video',
        topic: '',
        material: [],
        reference: null,
        script: null,
        stage: 'draft',
        scene_order: [],
        scenes: {},
        settings: preset === null ? template.settings : { ...template.settings, ...preset?.settings },
      };
      videos.set(created.id, { created, draftMessage: null });
      return { ...fixture, body: created };
    }
    if (request.method === 'POST' && area === 'projects' && id !== undefined && resource === 'presets') {
      const { video_id: videoId, name } = request.body as { video_id: string; name: string };
      const video = videos.get(videoId)?.created;
      if (video?.project_id !== id) return { status: 404, headers: {}, body: null };
      const { audio, caption, extra_instructions, format, locks, motion, visual } = editedVideoSettings.get(videoId) ?? video.settings;
      const { font_id, highlight, mode, position, typing_sound } = caption;
      const preset: Preset = {
        ...(fixture.body as Preset),
        id: nextId('ps'),
        project_id: id,
        name,
        settings: { audio, caption: { font_id, highlight, mode, position, typing_sound }, extra_instructions, format, locks, motion, visual },
      };
      presets.set(preset.id, preset);
      return { ...fixture, body: preset };
    }
    const video = area === 'videos' && id !== undefined ? videos.get(id) : undefined;
    if (video !== undefined && request.method === 'POST' && resource === 'draft') {
      const { message } = request.body as { message: string };
      video.draftMessage = message;
      const job: Job = {
        ...(fixture.body as Job),
        id: nextId('j'),
        project_id: video.created.project_id,
        video_id: video.created.id,
      };
      draftJobs.set(job.id, { job, queuedAt: Date.now(), revision: video.created.revision });
      return { ...fixture, body: job };
    }
    if (video !== undefined && request.method === 'GET' && resource === undefined) {
      const template = fixture.body as VideoView;
      return {
        ...fixture,
        body: {
          ...template,
          video: video.draftMessage === null ? video.created : {
            ...withMockStory(template.video),
            id: video.created.id,
            project_id: video.created.project_id,
            topic: video.draftMessage,
            settings: video.created.settings,
          },
          build: {
            ...(video.draftMessage === null ? template.build : withMockStoryStills(template.build, template.video)),
            video_id: video.created.id,
          },
        } satisfies VideoView,
      };
    }
    if (request.method === 'GET' && area === 'jobs') {
      if (id === undefined && request.query?.video_id !== undefined) {
        return { ...fixture, body: {
          items: [...draftJobs.values()].map(settled).filter((job) => job.video_id === request.query?.video_id),
          next_cursor: null,
        } };
      }
      const queued = id === undefined ? undefined : draftJobs.get(id);
      if (queued !== undefined) return { ...fixture, body: settled(queued) };
    }
    return fixture;
  });
}

export const mockFixtureCount = fixtures.length;
