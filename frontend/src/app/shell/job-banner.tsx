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
