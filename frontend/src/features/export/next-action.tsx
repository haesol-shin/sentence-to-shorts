import { Button } from '@/components/Button/Button';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { useLocale } from '@/shared/lib/i18n/locale';

import { downloadUrl } from './api';
import { startDownload } from './download';
import { srtReady } from './model';
import { useExportState } from './store';

/**
 * The caption file button beside the mp4 seat, named for the file's use only;
 * the file type stays in the tooltip. It waits until the caption file exists.
 */
function CaptionSave({ videoId, ready }: { videoId: string | null; ready: boolean }) {
  const { t } = useLocale();
  const button = (
    <Button
      variant="ghost"
      className="shrink-0 whitespace-nowrap"
      disabled={!ready}
      onClick={() => {
        if (ready && videoId !== null) startDownload(downloadUrl(videoId, 'srt'));
      }}
    >
      {t('export.caption.save')}
    </Button>
  );
  // The seat mounts before the file exists; a fresh tooltip per state keeps it bound to the current trigger.
  return (
    <Tooltip key={ready ? 'ready' : 'waiting'} content={t('export.caption.saveReason')} side="bottom">
      {ready ? button : <span tabIndex={0} className="inline-flex shrink-0">{button}</span>}
    </Tooltip>
  );
}

/**
 * The top bar seat of the export step: the caption file button and a named
 * primary button that saves the mp4. Until a file exists its button stays
 * dimmed and the reason shows on hover and on focus. A result is downloadable
 * only for the current workspace video.
 */
export function ExportNextAction({ videoId }: { videoId: string | null }) {
  const { t } = useLocale();
  const state = useExportState();
  const current = videoId !== null && state.videoId === videoId;
  const ready = current && state.phase === 'ready';

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

  return (
    <>
      <CaptionSave videoId={videoId} ready={current && srtReady(state.view)} />
      {ready ? (
        button
      ) : (
        <Tooltip content={t('export.save.mp4Reason')} side="bottom">
          <span tabIndex={0} className="inline-flex shrink-0" data-slot="next-action-seat">
            {button}
          </span>
        </Tooltip>
      )}
    </>
  );
}
