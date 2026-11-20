import { useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/Button/Button';
import { EmptyState } from '@/components/EmptyState/EmptyState';
import { Notice } from '@/components/Notice/Notice';
import { ApiProblemError, type Job, type Preset } from '@/shared/api/client';
import { useLocale } from '@/shared/lib/i18n/locale';

import { flushActivity } from './activity';
import { finalArtifactId, hasTokens, jobUsageMetrics } from './model';
import { PrecheckPanel } from './precheck-panel';
import { ResultCard } from './result-card';
import { Attribution, ResultFacts, UsageSection } from './result-facts';
import { ResultPlayer } from './result-player';
import { SceneRail } from './scene-rail';
import {
  closeCard,
  refreshMetrics,
  reloadExport,
  retryPrecheck,
  saveForNextVideo,
  useExportState,
} from './store';
import './export.css';

/** The longest name a saved next-video setting may have. */
const NAME_LIMIT = 60;

const GENERATION_STAGES: Partial<Record<NonNullable<Job['progress']['stage']>, string>> = {
  tts: 'voice',
  align: 'captions',
  layer: 'scenes',
  still: 'scenes',
  clip: 'scenes',
  mix: 'sound',
  assemble: 'assemble',
  srt: 'captions',
};

/**
 * The export step. It reads the video the edit step made: before the mp4
 * exists it shows the check before output, while a job runs it only says so
 * (the progress belongs to the top bar of the edit step) and once the mp4 is
 * there it shows the player, the facts, the time and usage, and the result card.
 */
export function ExportScreen({
  unseen,
  onPickScene,
  onEdit,
  onStart,
  onRetryGeneration,
  onSavePreset,
  jobReadFailed,
}: {
  /** Scenes with a change the user has not looked at yet. */
  unseen: readonly string[];
  /** A scene the user pressed to change; the caller makes it the request target. */
  onPickScene: (sceneId: string) => void;
  onEdit: () => void;
  onStart: (revision: number) => Promise<boolean>;
  onRetryGeneration: (job: Job) => Promise<boolean>;
  onSavePreset: (preset: Preset) => void;
  jobReadFailed: boolean;
}) {
  const { t } = useLocale();
  const state = useExportState();
  const usage = useRef<HTMLElement>(null);
  const [playerSeconds, setPlayerSeconds] = useState<number | null>(null);
  const [submission, setSubmission] = useState<'idle' | 'starting' | 'failed' | 'not-retryable'>('idle');
  const { videoId, phase } = state;
  const measured = useMemo(() => jobUsageMetrics(videoId ?? '', state.history), [videoId, state.history]);
  const tokens = hasTokens(state.metrics)
    ? { input: state.metrics.input_tokens, output: state.metrics.output_tokens }
    : measured.tokens;
  useEffect(() => {
    if (phase === 'ready' && videoId !== null) flushActivity(videoId);
  }, [phase, videoId]);

  const view = state.view;
  const artifactId = finalArtifactId(view);
  const estimated = view !== null && view.build.estimated_ms > 0 ? Math.round(view.build.estimated_ms / 1000) : null;
  const seconds = playerSeconds ?? estimated;
  const exact = playerSeconds !== null;

  const submit = async (action: () => Promise<boolean>) => {
    if (submission === 'starting') return;
    setSubmission('starting');
    try {
      if (await action()) {
        setSubmission('idle');
        onEdit();
      } else {
        setSubmission('failed');
      }
    } catch (error) {
      setSubmission(error instanceof ApiProblemError && error.code === 'job_not_retryable'
        ? 'not-retryable'
        : 'failed');
    }
  };

  const showUsage = () => {
    closeCard();
    if (state.videoId !== null) flushActivity(state.videoId);
    refreshMetrics();
    window.requestAnimationFrame(() => {
      usage.current?.scrollIntoView?.({ block: 'center' });
      usage.current?.focus();
    });
  };

  const body = (() => {
    if (state.phase === 'empty' || (state.phase === 'idle' && view?.video.scene_order.length === 0)) {
      return (
        <EmptyState
          title={t('export.empty.title')}
          actions={<Button onClick={onEdit}>{t('export.toEdit')}</Button>}
        >
          {t('export.empty.body')}
        </EmptyState>
      );
    }
    if (state.phase === 'loading') {
      return (
        <p role="status" className="export-muted">
          {t('export.loading')}
        </p>
      );
    }
    if (state.phase === 'failed' || view === null) {
      return (
        <EmptyState
          tone="error"
          title={t('export.failed.title')}
          actions={<Button onClick={reloadExport}>{t('export.failed.retry')}</Button>}
        >
          {t('export.failed.body')}
        </EmptyState>
      );
    }
    if (state.phase === 'making') {
      return (
        <EmptyState
          title={t('export.making.title')}
          actions={<Button variant="secondary" onClick={onEdit}>{t('export.toEdit')}</Button>}
        >
          {t('export.making.body')}
          {jobReadFailed ? ` ${t('export.generation.readFailed')}` : null}
        </EmptyState>
      );
    }
    if (state.phase === 'incomplete' && state.stopped !== null) {
      const job = state.stopped;
      const failed = job.state === 'failed';
      const stage = job.error?.stage ?? job.progress.stage;
      const label = stage === null ? undefined : GENERATION_STAGES[stage];
      const canRetry = job.attempt < job.max_attempts && (!failed || job.error?.retryable === true)
        && submission !== 'not-retryable';
      return (
        <EmptyState
          tone={failed ? 'error' : 'neutral'}
          title={t(failed ? 'export.generation.failed' : 'export.generation.cancelled')}
          actions={
            <>
              <Button variant="secondary" onClick={onEdit}>{t('export.toEdit')}</Button>
              {canRetry ? (
                <Button disabled={submission === 'starting'} onClick={() => void submit(() => onRetryGeneration(job))}>
                  {t('export.generation.retry')}
                </Button>
              ) : null}
            </>
          }
        >
          {label === undefined ? null : t('export.generation.stage', { stage: t(`export.generation.${label}`) })}
          {submission === 'not-retryable' ? ` ${t('export.generation.notRetryable')}` : null}
          {submission === 'failed' ? ` ${t('export.start.failed')}` : null}
        </EmptyState>
      );
    }
    if (state.phase === 'idle') {
      return (
        <PrecheckPanel
          view={view}
          status={state.precheck.status}
          report={state.precheck.report}
          starting={submission === 'starting'}
          startFailed={submission === 'failed'}
          onRetry={retryPrecheck}
          onStart={() => void submit(() => onStart(view.video.revision))}
          onEdit={onEdit}
        />
      );
    }
    return null;
  })();

  const name = Array.from(view?.video.topic.trim() ?? '').slice(0, NAME_LIMIT).join('') || t('export.next.name');

  return (
    <section
      data-slot="stage-panel"
      data-stage="export"
      data-phase={state.phase}
      aria-label={t('export.screen')}
      className="export-stage"
    >
      {view === null || state.phase === 'loading' ? null : (
        <SceneRail view={view} unseen={unseen} onPick={onPickScene} />
      )}
      {view !== null && state.phase === 'ready' && artifactId !== null ? (
        <>
          <div data-slot="export-main" className="export-main">
            <h2 className="export-title">{t('export.card.title')}</h2>
            <ResultPlayer artifactId={artifactId} estimateSeconds={estimated} onDuration={setPlayerSeconds} />
          </div>
          <div data-slot="export-panel" className="export-panel">
            <p className="export-muted">{t('export.card.description')}</p>
            <ResultFacts
              view={view}
              seconds={seconds}
              exact={exact}
              tokens={tokens}
              onShowUsage={showUsage}
            />
            <div className="export-actions export-actions--start">
              <Button variant="secondary" onClick={onEdit}>
                {t('export.toEdit')}
              </Button>
            </div>
            <UsageSection ref={usage} videoId={view.video.id} metrics={state.metrics} measured={measured} tokens={tokens} />
            <Attribution view={view} />
            <section data-slot="export-next" className="export-section">
              <h3 className="export-section__title">{t('export.next.title')}</h3>
              <div className="export-actions export-actions--start">
                <Button
                  variant="secondary"
                  disabled={state.preset === 'saving'}
                  onClick={() => saveForNextVideo(name, onSavePreset)}
                >
                  {state.preset === 'saving' ? t('export.next.saving') : t('export.next.save')}
                </Button>
              </div>
              {state.preset === 'saved' ? (
                <Notice>{t('export.next.saved')}</Notice>
              ) : state.preset === 'failed' ? (
                <Notice tone="error">{t('export.next.failed')}</Notice>
              ) : null}
            </section>
          </div>
          <ResultCard
            open={state.cardOpen}
            view={view}
            artifactId={artifactId}
            seconds={seconds}
            exact={exact}
            tokens={tokens}
            onDuration={setPlayerSeconds}
            onClose={closeCard}
            onEdit={() => {
              closeCard();
              onEdit();
            }}
            onShowUsage={showUsage}
          />
        </>
      ) : (
        <div data-slot="export-main" className="export-main export-main--wide">
          {body}
        </div>
      )}
    </section>
  );
}
