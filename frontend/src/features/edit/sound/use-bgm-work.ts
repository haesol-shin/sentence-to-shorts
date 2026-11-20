import { useEffect, useRef, useState } from 'react';

import { EditApiError, type BgmChoice, type Job } from '../api';
import type { EditValue } from '../edit-context';
import { bgmChange, readAudio, trackPatch } from './model';

const POLL_MS = 250;
type WorkKind = 'upload' | 'code';
type WorkInput = Pick<EditValue, 'audio' | 'video' | 'applySettings' | 'settingsBusy'>;

interface Operation {
  kind: WorkKind;
  id: string | null;
  stopRequested: boolean;
  cancelRequest: Promise<void> | null;
}

interface CompletedTrack {
  videoId: string;
  track: BgmChoice;
}

export interface BgmWork {
  running: WorkKind | null;
  stopping: boolean;
  waitingToApply: boolean;
  error: { kind: WorkKind; key: string } | null;
  upload: (file: File, isAudio: boolean) => void;
  generate: () => void;
  stop: () => void;
  dismiss: () => void;
}

export const EMPTY_BGM_WORK: BgmWork = {
  running: null,
  stopping: false,
  waitingToApply: false,
  error: null,
  upload: () => undefined,
  generate: () => undefined,
  stop: () => undefined,
  dismiss: () => undefined,
};

function active(job: Job) {
  return job.state === 'queued' || job.state === 'running' || job.state === 'cancelling';
}

function errorKey(error: unknown, kind: WorkKind): string {
  if (kind === 'upload' && error instanceof EditApiError) {
    if (error.code === 'payload_too_large') return 'audio.bgm.error.tooLarge';
    if (error.code === 'unsupported_media') return 'audio.bgm.error.unsupported';
    if (error.code === 'validation_failed') return 'audio.bgm.error.invalid';
  }
  return 'audio.bgm.error.failed';
}

const BUSY_KEY = 'audio.bgm.error.busy';

/** The edit provider owns the job and completed track, independently of its active tab. */
export function useBgmWork({ audio, video, applySettings, settingsBusy }: WorkInput): BgmWork {
  const videoId = video?.id;
  const operation = useRef<Operation | null>(null);
  const [running, setRunning] = useState<WorkKind | null>(null);
  const [stopping, setStopping] = useState(false);
  const pendingTrack = useRef<CompletedTrack | null>(null);
  const [completed, setCompleted] = useState<CompletedTrack | null>(null);
  const [error, setError] = useState<BgmWork['error']>(null);

  useEffect(() => {
    setRunning(null);
    setStopping(false);
    setCompleted(null);
    setError(null);
    return () => {
      operation.current = null;
      pendingTrack.current = null;
    };
  }, [videoId]);

  useEffect(() => {
    if (completed === null || completed !== pendingTrack.current ||
      completed.videoId !== video?.id || settingsBusy) return;
    pendingTrack.current = null;
    setCompleted(null);
    setError((current) => (current?.key === BUSY_KEY ? null : current));
    applySettings(bgmChange(video, trackPatch(completed.track)));
  }, [applySettings, completed, settingsBusy, video]);

  const cancel = (work: Operation) => {
    if (work.id === null || work.cancelRequest !== null) return;
    work.cancelRequest = audio.cancelJob(work.id).then(
      () => undefined,
      (failure: unknown) => {
        if (operation.current !== work) return;
        if (failure instanceof EditApiError && failure.code === 'job_terminal') return;
        setError({ kind: work.kind, key: 'audio.bgm.error.stop' });
        setStopping(false);
        work.stopRequested = false;
        work.cancelRequest = null;
      },
    );
  };

  const run = async (kind: WorkKind, start: () => Promise<Job>) => {
    if (videoId === undefined || operation.current !== null || completed !== null) return;
    const work: Operation = { kind, id: null, stopRequested: false, cancelRequest: null };
    operation.current = work;
    setError(null);
    setRunning(kind);
    try {
      let job = await start();
      if (operation.current !== work) return;
      work.id = job.id;
      if (work.stopRequested && active(job)) cancel(work);
      while (operation.current === work && active(job)) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, POLL_MS));
        if (operation.current !== work) return;
        job = await audio.readJob(job.id);
      }
      if (operation.current !== work || job.state === 'cancelled') return;
      if (job.state !== 'succeeded') {
        const code = job.error?.code;
        const key = kind === 'upload' && (code === 'upload_invalid' || code === 'media_invalid_input')
          ? 'audio.bgm.error.invalid' : 'audio.bgm.error.failed';
        setError({ kind, key });
        return;
      }
      const tracks = await audio.reloadBgm();
      if (work.cancelRequest !== null) await work.cancelRequest;
      if (operation.current !== work) return;
      const track = tracks.find((entry) => entry.id === job.result?.['bgm_id']);
      if (track === undefined) {
        const key = kind === 'upload' ? 'audio.bgm.error.uploadNotListed' : 'audio.bgm.error.failed';
        setError({ kind, key });
        return;
      }
      if (!work.stopRequested) {
        const result = { videoId, track };
        pendingTrack.current = result;
        setCompleted(result);
      }
    } catch (failure) {
      if (operation.current === work) setError({ kind, key: errorKey(failure, kind) });
    } finally {
      if (operation.current === work) {
        operation.current = null;
        setRunning(null);
        setStopping(false);
        setError((current) => (current?.key === BUSY_KEY ? null : current));
      }
    }
  };

  const mood = readAudio(video).bgm.mood;
  return {
    running,
    stopping,
    waitingToApply: completed?.videoId === videoId && completed !== null,
    error,
    upload: (file, isAudio) => {
      if (operation.current !== null || completed !== null) {
        setError({ kind: 'upload', key: BUSY_KEY });
        return;
      }
      if (!isAudio || file.size === 0) {
        setError({
          kind: 'upload',
          key: isAudio ? 'audio.bgm.error.invalid' : 'audio.bgm.error.unsupported',
        });
        return;
      }
      void run('upload', () => audio.uploadBgm(file, mood));
    },
    generate: () => { void run('code', () => audio.generateBgm(mood, null)); },
    stop: () => {
      const work = operation.current;
      if (work === null || work.stopRequested) return;
      work.stopRequested = true;
      setStopping(true);
      void cancel(work);
    },
    dismiss: () => setError(null),
  };
}
