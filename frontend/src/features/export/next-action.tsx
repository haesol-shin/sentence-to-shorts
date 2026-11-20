import { Button } from '@/components/Button/Button';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { useLocale } from '@/shared/lib/i18n/locale';

import { downloadUrl } from './api';
import { startDownload } from './download';
import { useExportState } from './store';

/**
 * The top bar seat of the export step: a named primary button that saves the
 * mp4. Until the file exists it stays dimmed and the reason shows on hover and
 * on focus. A result is downloadable only for the current workspace video.
 */
export function ExportNextAction({ videoId }: { videoId: string | null }) {
  const { t } = useLocale();
  const state = useExportState();
  const ready = videoId !== null && state.videoId === videoId && state.phase === 'ready';

  const button = (
    <Button
      data-slot="next-action"
      className="min-w-[calc(var(--space-48)*3)] shrink-0 px-4 whitespace-nowrap"
      disabled={!ready}
      onClick={() => {
        if (ready) startDownload(downloadUrl(videoId, 'mp4'));
      }}
    >
      {t('export.save.mp4')}
    </Button>
  );

  return ready ? (
    button
  ) : (
    <Tooltip content={t('export.save.mp4Reason')} side="bottom">
      <span tabIndex={0} className="inline-flex shrink-0" data-slot="next-action-seat">
        {button}
      </span>
    </Tooltip>
  );
}
