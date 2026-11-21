import type { Language, PrepareErrorCode, PrepareGroup, PrepareGroupId } from '@/shared/api/client';

/**
 * What a make-video button waits for. A Korean video needs the voice models; an
 * English one also needs the English aligner. The transcriber is for reference
 * videos and starts on the server, so no button reads it.
 */
const NEEDED: Record<Language, readonly PrepareGroupId[]> = {
  ko: ['voice'],
  en: ['voice', 'align_en'],
};

/**
 * The state of the needed groups as one answer. `waiting` covers queued and
 * downloading, where the button stays pressable and shows the percent.
 */
export type PrepareView =
  | { state: 'ready' }
  | { state: 'waiting'; percent: number }
  | { state: 'retrying'; percent: number; retryAt: string | null }
  | { state: 'failed'; percent: number; errorCode: PrepareErrorCode | null };

export const PREPARE_READY: PrepareView = { state: 'ready' };

/** Whether the buttons still wait for a model group. */
export function isPreparing(view: PrepareView): boolean {
  return view.state !== 'ready';
}

/** The percent a button shows while the models download or retry; `null` when it has nothing to show. */
export function waitingPercent(view: PrepareView): number | null {
  return view.state === 'waiting' || view.state === 'retrying' ? view.percent : null;
}

/**
 * Folds the groups a video needs into one view. A failed group outranks a
 * retrying one, which outranks a download in progress. A group the server does
 * not list has nothing to wait for. The percent is bytes done over bytes total
 * of the needed groups and never reads 100 until every group is ready.
 */
export function prepareOf(groups: readonly PrepareGroup[] | null, language: Language): PrepareView {
  if (groups === null) return PREPARE_READY;
  const needed = groups.filter((group) => NEEDED[language].includes(group.id));
  const open = needed.filter((group) => group.state !== 'ready');
  if (open.length === 0) return PREPARE_READY;

  const total = needed.reduce((sum, group) => sum + group.total, 0);
  const done = needed.reduce((sum, group) => sum + (group.state === 'ready' ? group.total : group.done), 0);
  const percent = total > 0 ? Math.min(99, Math.max(0, Math.floor((done / total) * 100))) : 0;

  const failed = open.find((group) => group.state === 'failed');
  if (failed !== undefined) return { state: 'failed', percent, errorCode: failed.error_code };
  const retrying = open.find((group) => group.state === 'retrying');
  if (retrying !== undefined) return { state: 'retrying', percent, retryAt: retrying.retry_at };
  return { state: 'waiting', percent };
}

/** The wall-clock time of the next attempt, in the screen language. */
export function clockOf(timestamp: string, language: Language): string | null {
  const at = new Date(timestamp);
  if (Number.isNaN(at.getTime())) return null;
  return at.toLocaleTimeString(language === 'ko' ? 'ko-KR' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
