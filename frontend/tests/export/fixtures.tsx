import { render } from '@testing-library/react';
import { vi, type Mock } from 'vitest';
import type { ReactNode } from 'react';

import type { ExportApi, Metrics, PrecheckReport } from '@/features/export/api';
import { ExportScreen } from '@/features/export/export-screen';
import { ExportNextAction } from '@/features/export/next-action';
import { configureExport, useExportSession } from '@/features/export/store';
import type { Job, VideoView } from '@/shared/api/client';
import { LocaleProvider } from '@/shared/lib/i18n/locale';

import { makeView } from '../edit/fixtures';

export const FINAL_ID = 'a_0final00000000000000000000';
export const SRT_ID = 'a_0srt0000000000000000000000';

const DIGEST = '0'.repeat(64);

function fresh(id: string) {
  return {
    state: 'fresh' as const,
    cache_key: DIGEST,
    artifact: { id, digest: DIGEST, cache_key: DIGEST },
    error_code: null,
  };
}

/** A video whose scenes are confirmed and whose mp4 does not exist yet. */
export function unbuiltView(): VideoView {
  const view = makeView();
  view.video.settings.caption = { mode: 'sentence', position: 'bottom', highlight: true } as never;
  view.video.material = [{ id: 'm_0material0000000000000000', text: '물의 온도를 93도로 맞춘다.' }];
  return view;
}

/** The same video once the mp4 and the caption file are made. */
export function builtView(): VideoView {
  const view = unbuiltView();
  view.build.final = fresh(FINAL_ID);
  view.build.srt = fresh(SRT_ID);
  view.build.estimated_ms = 23_000;
  view.build.actual_ms = 65_000;
  view.build.attribution = [{ ko: '배경 음악: 합성 곡 (CC BY 4.0)', en: 'Music: synthetic track (CC BY 4.0)' }];
  return view;
}

export function job(kind: Job['kind'], state: Job['state'], result: Job['result'] = null): Job {
  return {
    id: `j_0${kind}${state}`.padEnd(27, '0'),
    kind,
    owner_id: 'owner',
    state,
    project_id: 'p_0test00000000000000000000',
    video_id: 'v_0test00000000000000000000',
    base_revision: 1,
    request_digest: DIGEST,
    idempotency_key: null,
    attempt: 1,
    max_attempts: 3,
    created_at: '2026-11-20T00:00:00Z',
    started_at: null,
    ended_at: null,
    deadline_at: null,
    progress: { stage: null, done: 0, total: 0, waiting_on: null },
    stages: [],
    checkpoints: [],
    usage: [],
    result,
    error: null,
    partial: false,
  } as Job;
}

export const REPORT: PrecheckReport = {
  opening_promise: '커피를 고르는 기준 세 가지를 알려 준다',
  ending_answer: '그래서 기준은 원두, 물, 시간이다',
  claims: [
    { scene_id: 's_0scene2000000000000000000', text: '물은 93도가 좋다', material_id: 'm_0material0000000000000000' },
    { scene_id: 's_0scene3000000000000000000', text: '원두는 2주 안에 쓴다', material_id: null },
  ],
  hypotheticals: ['s_0scene1000000000000000000'],
};

export const METRICS: Metrics = {
  active_ms: 83_000,
  waiting_ms: 41_000,
  job_wall_ms: 39_000,
  input_tokens: 1240,
  output_tokens: 680,
  cost_micro_usd: 12_300,
  regenerated_scene_ids: ['s_0scene2000000000000000000'],
};

/** The API with every call a spy, so a test reads what the screen sent. */
export type StubApi = { [K in keyof ExportApi]: Mock<ExportApi[K]> };

export function stubApi(overrides: Partial<ExportApi> = {}): StubApi {
  const base: ExportApi = {
    loadVideo: vi.fn(async (_id: string, fallback: VideoView | null) => fallback ?? builtView()),
    readJob: vi.fn(async () => job('precheck', 'succeeded', { precheck: REPORT })),
    startPrecheck: vi.fn(async () => job('precheck', 'running')),
    jobs: vi.fn(async () => []),
    metrics: vi.fn(async () => METRICS),
    recordActivity: vi.fn(async () => undefined),
    savePreset: vi.fn(async (projectId: string, body: { video_id: string; name: string }) => ({ id: 'ps_0', project_id: projectId, name: body.name }) as never),
  };
  return { ...base, ...overrides } as never;
}

function Session({ view, children }: { view: VideoView; children: ReactNode }) {
  useExportSession(view.video.id, view);
  return <>{children}</>;
}

/** Renders the export screen and its top bar seat over one stubbed API. */
export function renderExport(
  view: VideoView,
  api: ExportApi,
  { unseen = [], onPickScene = () => undefined, onOpenEdit = () => undefined, onStart = async () => false,
    onRetryGeneration = async () => false, sameSession = false }: {
    unseen?: readonly string[];
    onPickScene?: (sceneId: string) => void;
    onOpenEdit?: () => void;
    onStart?: (revision: number) => Promise<boolean>;
    onRetryGeneration?: (job: Job) => Promise<boolean>;
    /** Keeps what the store already knows, as a visit back to the screen does. */
    sameSession?: boolean;
  } = {},
) {
  if (!sameSession) configureExport(api);
  return render(
    <LocaleProvider language="ko" setLanguage={() => undefined}>
      <Session view={view}>
        <ExportNextAction videoId={view.video.id} />
        <ExportScreen
          unseen={unseen}
          onPickScene={onPickScene}
          onEdit={onOpenEdit}
          onStart={onStart}
          onRetryGeneration={onRetryGeneration}
          onSavePreset={() => undefined}
          jobReadFailed={false}
        />
      </Session>
    </LocaleProvider>,
  );
}

