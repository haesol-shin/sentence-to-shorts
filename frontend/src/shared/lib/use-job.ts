import { useEffect, useState } from 'react';

import { messageKeyOf, readJob, type Job } from '@/shared/api/client';

export const POLL_VISIBLE_MS = 1000;
export const POLL_HIDDEN_MS = 5000;

/** CONTRACTS 3: one second while the tab is visible, five while it is hidden. */
export function pollDelay(visibility: DocumentVisibilityState): number {
  return visibility === 'hidden' ? POLL_HIDDEN_MS : POLL_VISIBLE_MS;
}

export interface JobFeed {
  job: Job | null;
  failureKey: string | null;
}

/**
 * Follows one job until it ends. Each read sends the ETag of the previous body,
 * so an unchanged job costs a 304 and no re-render.
 *
 * One read and one timer at most: a tab switch that lands while a read is out
 * only changes the delay used once that read answers, so two answers can never
 * cross and walk a finished job back to a waiting one.
 */
export function useJob(jobId: string | null): JobFeed {
  const [feed, setFeed] = useState<JobFeed>({ job: null, failureKey: null });

  useEffect(() => {
    if (jobId === null) {
      setFeed({ job: null, failureKey: null });
      return;
    }

    const controller = new AbortController();
    let etag: string | null = null;
    let timer: number | undefined;
    let reading = false;
    let stopped = false;

    const clearTimer = () => {
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
      }
    };

    const arm = () => {
      if (stopped || reading || controller.signal.aborted) {
        return;
      }
      clearTimer();
      timer = window.setTimeout(() => {
        timer = undefined;
        void tick();
      }, pollDelay(document.visibilityState));
    };

    const tick = async () => {
      if (reading || stopped) {
        return;
      }
      reading = true;
      try {
        const read = await readJob(jobId, etag, controller.signal);
        if (controller.signal.aborted) {
          return;
        }
        if (!read.notModified && read.job !== null) {
          etag = read.etag;
          setFeed({ job: read.job, failureKey: null });
          stopped =
            read.job.state === 'succeeded' ||
            read.job.state === 'failed' ||
            read.job.state === 'cancelled';
        }
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        setFeed((previous) => ({ job: previous.job, failureKey: messageKeyOf(error) }));
      } finally {
        reading = false;
        arm();
      }
    };

    const onVisibilityChange = () => {
      // A read already on its way re-arms itself when it answers.
      clearTimer();
      arm();
    };

    void tick();
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      controller.abort();
      clearTimer();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [jobId]);

  return feed;
}
