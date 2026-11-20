import { useEffect, useRef, useState } from 'react';

import { pollDelay } from '@/shared/lib/use-job';

import { EditApiError, type BgmChoice, type Job } from '../api';
import type { EditValue } from '../edit-context';
import { bgmChange, readAudio, trackPatch } from './model';

type WorkKind = 'upload' | 'code';
type WorkInput = Pick<EditValue, 'audio' | 'video' | 'applySettings' | 'settingsBusy'>;

interface Operation {
  kind: WorkKind;
  id: string | null;
  polling: AbortController;
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

function trackingEnded(result: Job | EditApiError): boolean {
  if (result instanceof EditApiError) {
    return result.code === 'job_terminal' || result.code === 'not_found' || result.status === 404;
  }
  return result.state === 'cancelled' || result.state === 'succeeded' || result.state === 'failed';
}

function jobFailureKey(job: Job, kind: WorkKind): string {
  const code = job.error?.code;
  return kind === 'upload' && (code === 'upload_invalid' || code === 'media_invalid_input')
    ? 'audio.bgm.error.invalid' : 'audio.bgm.error.failed';
}

function waitForPoll(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    let timer: number;
    const finish = () => {
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', schedule);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(finish, pollDelay(document.visibilityState));
    };
    document.addEventListener('visibilitychange', schedule);
    signal.addEventListener('abort', finish);
    schedule();
  });
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
const READ_STATUS_KEY = 'audio.bgm.error.readStatus';

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
      operation.current?.polling.abort();
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

  const finish = (work: Operation) => {
    if (operation.current !== work) return;
    operation.current = null;
    work.polling.abort();
    setRunning(null);
    setStopping(false);
    setError((current) => current?.key === BUSY_KEY || current?.key === READ_STATUS_KEY ? null : current);
  };

  const cancel = (work: Operation) => {
    if (work.id === null || work.cancelRequest !== null) return;
    work.cancelRequest = audio.cancelJob(work.id).then(
      (job) => {
        if (operation.current !== work || !trackingEnded(job)) return;
        if (job.state === 'failed') setError({ kind: work.kind, key: jobFailureKey(job, work.kind) });
        finish(work);
        if (job.state === 'succeeded') {
          void audio.reloadBgm().catch(() => { /* Catalog state owns the reload error. */ });
        }
      },
      (failure: unknown) => {
        if (operation.current !== work) return;
        if (failure instanceof EditApiError && trackingEnded(failure)) {
          if (failure.code !== 'job_terminal') {
            setError({ kind: work.kind, key: errorKey(failure, work.kind) });
          }
          finish(work);
          if (failure.code === 'job_terminal') {
            void audio.reloadBgm().catch(() => { /* Catalog state owns the reload error. */ });
          }
          return;
        }
        setError({ kind: work.kind, key: 'audio.bgm.error.stop' });
        setStopping(false);
        work.stopRequested = false;
        work.cancelRequest = null;
      },
    );
  };

  const run = async (kind: WorkKind, start: () => Promise<Job>) => {
    if (videoId === undefined || operation.current !== null || completed !== null) return;
    const work: Operation = {
      kind, id: null, polling: new AbortController(), stopRequested: false, cancelRequest: null,
    };
    operation.current = work;
    setError(null);
    setRunning(kind);
    try {
      let job = await start();
      if (operation.current !== work) return;
      work.id = job.id;
      if (work.stopRequested && !trackingEnded(job)) cancel(work);
      let readFailed = false;
      while (operation.current === work && !trackingEnded(job)) {
        await waitForPoll(work.polling.signal);
        if (operation.current !== work) return;
        try {
          job = await audio.readJob(work.id);
          if (readFailed && operation.current === work) {
            readFailed = false;
            setError((current) => current?.key === READ_STATUS_KEY ? null : current);
          }
        } catch (failure) {
          if (operation.current !== work) return;
          if (!(failure instanceof EditApiError) || trackingEnded(failure) ||
            (failure.status !== 0 && (failure.status < 500 || failure.status >= 600))) throw failure;
          readFailed = true;
          setError((current) => current ?? { kind, key: READ_STATUS_KEY });
        }
      }
      if (operation.current !== work || job.state === 'cancelled') return;
      if (job.state !== 'succeeded') {
        setError({ kind, key: jobFailureKey(job, kind) });
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
      finish(work);
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
