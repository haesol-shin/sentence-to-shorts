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
 * The same status cut to one line for the phone top bar, where the header is
 * gone while the keys are up. It is the live region in that state, so the
 * label stays in the DOM for a screen reader but gives way to the text.
 */
export function JobStatusShort({ job }: { job: Job }) {
  const { t } = useLocale();
  return (
    <div
      data-slot="job-status"
      data-state={job.state}
      aria-live="polite"
      className="min-w-0 truncate text-[15px] text-[var(--text-muted)]"
    >
      <span className="sr-only">{t('shell.job.label')} </span>
      {jobText(t, job)}
    </div>
  );
}

/** One line about the running job, read out when it changes. */
export function JobBanner({ job }: { job: Job }) {
  const { t } = useLocale();
  return (
    <div
      data-slot="job-banner"
      data-state={job.state}
      aria-live="polite"
      className="flex items-center gap-2 bg-[var(--surface-muted)] px-4 py-2 text-[15px] text-[var(--text)]"
    >
      <span className="font-bold text-[var(--text-strong)]">{t('shell.job.label')}</span>
      <span>{jobText(t, job)}</span>
    </div>
  );
}
