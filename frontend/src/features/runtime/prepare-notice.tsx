import { Button } from '@/components/Button/Button';
import { Notice } from '@/components/Notice/Notice';
import { useLocale } from '@/shared/lib/i18n/locale';
import { cn } from '@/shared/lib/utils';

import { clockOf } from './prepare';
import type { PrepareStatus } from './use-prepare';

/**
 * The one sentence a make-video button owes the user when the models cannot
 * move: the connection is down and the download retries (with the time of the
 * next try), or it stopped for a reason named by the server code and the user
 * can start it again. When that retry request itself fails, its own failure
 * sentence replaces the stop reason. Nothing shows while the models download or are ready.
 */
export function PrepareNotice({ status, className }: { status: PrepareStatus; className?: string }) {
  const { t, language } = useLocale();
  const { view } = status;
  if (view.state !== 'retrying' && view.state !== 'failed') return null;

  if (view.state === 'retrying') {
    const time = view.retryAt === null ? null : clockOf(view.retryAt, language);
    return (
      <div className={className} data-slot="prepare-notice" data-state="retrying">
        <Notice>
          {t('shell.prepare.retrying')}
          {time === null ? null : <span className="block">{t('shell.prepare.retryAt', { time })}</span>}
        </Notice>
      </div>
    );
  }

  return (
    <div className={cn('flex flex-col items-end gap-2', className)} data-slot="prepare-notice" data-state="failed">
      <Notice tone="error">
        {status.retryError === null
          ? t(`shell.prepare.error.${view.errorCode ?? 'unknown'}`)
          : t(`errors.${status.retryError}`)}
      </Notice>
      <Button variant="secondary" size="sm" disabled={status.retrying} onClick={status.retry}>
        {t('shell.prepare.retry')}
      </Button>
    </div>
  );
}
