import { API_BASE, setTransport, type ApiRequest, type ApiResponse, type Job, type Preset, type Video, type VideoView } from '../client';
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

/** Uses recorded answers for static resources and isolates each video started in the app. */
export function installMockApi(): void {
  const videos = new Map<string, { created: Video; draftMessage: string | null }>();
  const draftJobs = new Map<string, QueuedDraft>();
  const presets = new Map<string, Preset>();
  let sequence = 0;
  editedVideoSettings.clear();
  const nextId = (prefix: string) => `${prefix}_${(++sequence).toString(32).padStart(25, '0')}`;

  setTransport(async (request) => {
    const fixture = mockResponse(request);
    const [, area, id, resource] = request.path.split('/');
    if (fixture.status >= 400) return fixture;
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
            ...template.video,
            id: video.created.id,
            project_id: video.created.project_id,
            topic: video.draftMessage,
            settings: video.created.settings,
          },
          build: { ...template.build, video_id: video.created.id },
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
