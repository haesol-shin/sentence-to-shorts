import { useLayoutEffect, useRef, useSyncExternalStore } from 'react';

import { MAX_ACTIVITY_SPANS, type ActivitySpan } from './api';
import { activityKind, ActivityTracker } from './model';
import { exportApi, refreshMetrics } from './store';

/** Bounds the amount of open time not yet journaled during a long visit. */
export const ACTIVITY_FLUSH_MS = 30_000;

const STORAGE_PREFIX = 'export.activity.v1:';

interface Journal {
  queued: ActivitySpan[];
  unconfirmed: ActivitySpan[][];
}

interface Report extends Journal {
  tracker: ActivityTracker | null;
  sending: boolean;
  storedQueue: boolean;
}

const reports = new Map<string, Report>();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function notify(): void {
  listeners.forEach((listener) => listener());
}

function isSpan(value: unknown): value is ActivitySpan {
  if (typeof value !== 'object' || value === null) return false;
  const { kind, start_ms, end_ms } = value as Partial<ActivitySpan>;
  return (kind === 'active' || kind === 'waiting')
    && typeof start_ms === 'number' && Number.isSafeInteger(start_ms) && start_ms >= 0
    && typeof end_ms === 'number' && Number.isSafeInteger(end_ms) && end_ms > start_ms;
}

function readJournal(videoId: string): Journal {
  try {
    // Tab-scoped storage survives a reload without sharing a send queue between tabs.
    const saved = JSON.parse(window.sessionStorage.getItem(STORAGE_PREFIX + videoId) ?? 'null') as Partial<Journal> | null;
    if (Array.isArray(saved?.queued) && Array.isArray(saved.unconfirmed)) {
      return {
        queued: saved.queued.filter(isSpan),
        unconfirmed: saved.unconfirmed
          .filter(Array.isArray)
          .map((batch) => batch.filter(isSpan))
          .filter((batch) => batch.length > 0),
      };
    }
  } catch {
    // Storage can be unavailable or contain a discarded format.
  }
  return { queued: [], unconfirmed: [] };
}

function reportFor(videoId: string): Report {
  let report = reports.get(videoId);
  if (report === undefined) {
    const journal = readJournal(videoId);
    report = { ...journal, tracker: null, sending: false, storedQueue: journal.queued.length > 0 };
    reports.set(videoId, report);
  }
  return report;
}

function persist(videoId: string, report: Report): boolean {
  try {
    const key = STORAGE_PREFIX + videoId;
    const { queued, unconfirmed } = report;
    if (queued.length === 0 && unconfirmed.length === 0) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, JSON.stringify({ queued, unconfirmed }));
    report.storedQueue = queued.length > 0;
    return true;
  } catch {
    return false;
  }
}

function enqueue(videoId: string, report: Report, spans: readonly ActivitySpan[]): void {
  if (spans.length === 0) return;
  report.queued.push(...spans);
  persist(videoId, report);
  notify();
}

async function sendBatch(videoId: string, report: Report): Promise<void> {
  if (report.sending || report.queued.length === 0) return;
  const queued = report.queued;
  const batch = queued.slice(0, MAX_ACTIVITY_SPANS);
  report.queued = queued.slice(batch.length);
  // Journal the batch as unconfirmed before POSTing. A lost response or reload
  // cannot tell us whether the additive endpoint already accepted these spans.
  report.unconfirmed.push(batch);
  if (!persist(videoId, report) && report.storedQueue) {
    // If the old queue may survive a reload, do not send it without journaling.
    report.queued = queued;
    report.unconfirmed.pop();
    return;
  }
  report.sending = true;
  try {
    await exportApi().recordActivity(videoId, batch);
  } catch {
    report.sending = false;
    return;
  }
  report.unconfirmed.pop();
  report.sending = false;
  persist(videoId, report);
  refreshMetrics(videoId);
  notify();
}

/** Snapshot any open span and attempt one batch. Batches in flight are never resent. */
export function flushActivity(videoId: string): void {
  const report = reportFor(videoId);
  enqueue(videoId, report, report.tracker?.take(Date.now()) ?? []);
  void sendBatch(videoId, report);
}

export function useActivityUnsent(videoId: string): boolean {
  return useSyncExternalStore(
    subscribe,
    () => {
      const report = reports.get(videoId) ?? readJournal(videoId);
      return report.queued.length > 0 || report.unconfirmed.length > 0;
    },
    () => false,
  );
}

/** Mount once per workspace. Screen transitions do not interrupt the current span. */
export function useActivityReporting(videoId: string | null, waiting: boolean, enabled = true): void {
  const waitingRef = useRef(waiting);
  const sync = useRef<(() => void) | null>(null);

  useLayoutEffect(() => {
    waitingRef.current = waiting;
    sync.current?.();
  }, [waiting]);

  useLayoutEffect(() => {
    if (videoId === null || !enabled) return undefined;
    const report = reportFor(videoId);
    const tracker = new ActivityTracker();
    report.tracker = tracker;
    let pageHidden = false;
    const visible = () => !pageHidden && document.visibilityState === 'visible';
    const syncKind = () => {
      const now = Date.now();
      tracker.update(activityKind(visible(), waitingRef.current), now);
      enqueue(videoId, report, tracker.takeClosed());
    };
    const flush = () => flushActivity(videoId);
    const onVisibility = () => {
      syncKind();
      if (!visible()) flush();
    };
    const onPageHide = () => {
      pageHidden = true;
      onVisibility();
    };
    const onPageShow = () => {
      pageHidden = false;
      syncKind();
    };

    sync.current = syncKind;
    syncKind();
    void sendBatch(videoId, report);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('pageshow', onPageShow);
    window.addEventListener('online', flush);
    const timer = window.setInterval(flush, ACTIVITY_FLUSH_MS);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onPageHide);
      window.removeEventListener('pageshow', onPageShow);
      window.removeEventListener('online', flush);
      window.clearInterval(timer);
      sync.current = null;
      onPageHide();
      report.tracker = null;
    };
  }, [videoId, enabled]);
}
