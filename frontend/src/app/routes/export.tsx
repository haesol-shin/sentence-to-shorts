import { useEffect } from 'react';

import { useEditOptional } from '@/features/edit/edit-context';
import { ExportScreen } from '@/features/export/export-screen';
import { inFlight } from '@/features/export/model';
import { useExportSession } from '@/features/export/store';
import { waitingPercent } from '@/features/runtime/prepare';
import { PrepareNotice } from '@/features/runtime/prepare-notice';
import { usePrepare } from '@/features/runtime/use-prepare';
import type { Preset } from '@/shared/api/client';

import type { Stage } from '../shell/shell-config';

export function ExportRoute({ videoId, onStage, onSavePreset }: {
  videoId: string | null;
  onStage: (stage: Stage) => void;
  onSavePreset: (preset: Preset) => void;
}) {
  const edit = useEditOptional();
  const current = edit?.view?.video.id === videoId ? edit : null;
  const prepare = usePrepare(current?.video?.settings.language ?? null);
  const generation = current?.job?.kind === 'generate' ? current.job : null;
  const job = generation !== null && (
    inFlight(generation) || generation.state === 'succeeded' || generation.base_revision === current?.view?.video.revision
  ) ? generation : null;
  const waiting = job !== null && (inFlight(job) || (
    job.state === 'succeeded' && current?.finishedGeneration !== job.id
  ));
  const loadingWorkspace = videoId !== null && current === null && edit !== null && edit.error === null;
  const proposed = current?.pending != null;
  // A proposal to confirm is reviewed in the edit screen, so a result-side request never waits on a missing button.
  useEffect(() => {
    if (proposed) onStage('edit');
  }, [proposed, onStage]);
  useExportSession(videoId, current?.view ?? null, waiting ? null : job, waiting, loadingWorkspace);

  return (
    <ExportScreen
      unseen={current?.unseen ?? []}
      onPickScene={(sceneId) => current?.selectScene(sceneId)}
      onEdit={() => onStage('edit')}
      onStart={(revision) => current?.generateVideo(revision) ?? Promise.resolve(false)}
      onRetryGeneration={(stopped) => current?.retryGeneration(stopped) ?? Promise.resolve(false)}
      onSavePreset={onSavePreset}
      jobReadFailed={current?.jobReadFailed === true}
      preparePercent={waitingPercent(prepare.view)}
      prepareNotice={<PrepareNotice status={prepare} className="flex justify-end" />}
    />
  );
}
