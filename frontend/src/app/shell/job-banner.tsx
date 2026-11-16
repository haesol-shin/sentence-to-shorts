import type { Job } from '@/shared/api/client';
import { useLocale, type Translate } from '@/shared/lib/i18n/locale';

function jobText(t: Translate, job: Job): string {
  switch (job.state) {
    case 'queued':
      return t('shell.job.queued');
    case 'running':
      return job.progress.total > 0
        ? t('shell.job.running', { done: job.progress.done, total: job.progress.total })
        : t('shell.job.runningNoTotal');
    case 'succeeded':
      return t('shell.job.succeeded');
    case 'cancelling':
      return t('shell.job.cancelling');
    case 'cancelled':
      return t('shell.job.cancelled');
    case 'failed':
      return t('shell.job.failed');
    default:
      return '';
  }
}

/**
 * The one live region for job status. It stays mounted while the keyboard opens
 * and closes, so a change that lands with a toggle is still read, and only once.
 */
export function JobAnnouncer({ job }: { job: Job | null }) {
  const { t } = useLocale();
  return (
    <div data-slot="job-live" aria-live="polite" className="sr-only">
      {job === null ? '' : `${t('shell.job.label')} ${jobText(t, job)}`}
    </div>
  );
}

/** The same status cut to one line for the phone top bar while the keys are up. */
export function JobStatusShort({ job }: { job: Job }) {
  const { t } = useLocale();
  return (
    <div
      data-slot="job-status"
      data-state={job.state}
      className="min-w-0 truncate text-[15px] text-[var(--text-muted)]"
    >
      {jobText(t, job)}
    </div>
  );
}

/** One line about the running job; the announcer reads its changes. */
export function JobBanner({ job }: { job: Job }) {
  const { t } = useLocale();
  return (
    <div
      data-slot="job-banner"
      data-state={job.state}
      className="flex items-center gap-2 bg-[var(--surface-muted)] px-4 py-2 text-[15px] text-[var(--text)]"
    >
      <span className="font-bold text-[var(--text-strong)]">{t('shell.job.label')}</span>
      <span>{jobText(t, job)}</span>
    </div>
  );
}
