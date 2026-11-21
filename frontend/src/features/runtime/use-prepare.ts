import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  getJson,
  messageKeyOf,
  retryRuntimePrepare,
  type Language,
  type PrepareGroup,
  type RuntimeStatus,
} from '@/shared/api/client';

import { isPreparing, prepareOf, type PrepareView } from './prepare';

/** The read interval while the tab is visible and while it is hidden. */
export const PREPARE_POLL_VISIBLE_MS = 1000;
export const PREPARE_POLL_HIDDEN_MS = 5000;

export interface PrepareStatus {
  view: PrepareView;
  /** Queues the failed groups again. */
  retry: () => void;
  /** The retry request is in flight. */
  retrying: boolean;
  /** The `errors` message key of the last retry request that failed; `null` when none stands. */
  retryError: string | null;
}

/**
 * Reads the model preparation of the groups a video of `language` waits for,
 * for every make-video button. It reads `GET /runtime` once, then keeps reading
 * every second (every five while the tab is hidden) only while a needed group
 * is not ready. A read that never answered counts as ready: the server holds a
 * job until its models are there, so the button never blocks on this reading.
 * `null` reads nothing. A retry request that fails is kept as `retryError` until
 * the next retry or until a read shows the needed groups are no longer failed.
 */
export function usePrepare(language: Language | null): PrepareStatus {
  const [groups, setGroups] = useState<readonly PrepareGroup[] | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const kick = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (language === null) return undefined;
    const needs: Language = language;
    const controller = new AbortController();
    let timer: number | undefined;
    let inFlight = false;
    let answered = false;
    let preparing = false;

    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(
        () => void read(),
        document.visibilityState === 'hidden' ? PREPARE_POLL_HIDDEN_MS : PREPARE_POLL_VISIBLE_MS,
      );
    };

    async function read(): Promise<void> {
      window.clearTimeout(timer);
      inFlight = true;
      try {
        const runtime = await getJson<RuntimeStatus>('/runtime', controller.signal);
        if (controller.signal.aborted) return;
        answered = true;
        const view = prepareOf(runtime.prepare.groups, needs);
        preparing = isPreparing(view);
        // A read that still shows the failure keeps the retry sentence: the retry did not move it.
        if (view.state !== 'failed') setRetryError(null);
        const next = runtime.prepare.groups;
        // Keep the old array when nothing changed, so a steady poll does not redraw the button.
        setGroups((current) => (JSON.stringify(current) === JSON.stringify(next) ? current : next));
      } catch {
        if (controller.signal.aborted) return;
      } finally {
        inFlight = false;
      }
      if (answered && preparing) schedule();
    }

    const onVisibility = () => {
      if (!inFlight && answered && preparing) schedule();
    };

    kick.current = () => {
      if (!inFlight) void read();
    };
    document.addEventListener('visibilitychange', onVisibility);
    void read();

    return () => {
      controller.abort();
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
      kick.current = () => undefined;
    };
  }, [language]);

  const view = useMemo(
    () => (language === null ? prepareOf(null, 'ko') : prepareOf(groups, language)),
    [groups, language],
  );

  const retry = useCallback(() => {
    setRetrying(true);
    setRetryError(null);
    retryRuntimePrepare()
      .catch((error: unknown) => setRetryError(messageKeyOf(error)))
      .finally(() => {
        setRetrying(false);
        kick.current();
      });
  }, []);

  return { view, retry, retrying, retryError };
}
