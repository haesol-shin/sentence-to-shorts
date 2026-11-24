import { Button } from '@/components/Button/Button';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Dialog, DialogClose } from '@/components/Dialog/Dialog';
import type { VideoView } from '@/shared/api/client';
import { useLocale } from '@/shared/lib/i18n/locale';

import { downloadUrl } from './api';
import { startDownload } from './download';
import type { TokenCounts } from './model';
import { ResultFacts } from './result-facts';
import { ResultPlayer } from './result-player';

const TITLE_ID = 'export-result-card-title';

/**
 * The card that opens when a video is ready, put together the way the
 * gallery assembles it: video and play row on the left; title, one sentence
 * and four fact lines stacked from the top on the right; only the button row
 * holds the bottom. The close x is the only close control, and its ring is
 * drawn inside so the card edge never cuts it. Every way out of the card
 * except the usage view lands on the edit screen's finished video.
 */
export function ResultCard({
  open,
  view,
  artifactId,
  seconds,
  exact,
  tokens,
  onDuration,
  onClose,
  onEdit,
  onShowUsage,
}: {
  open: boolean;
  view: VideoView;
  artifactId: string;
  seconds: number | null;
  exact: boolean;
  tokens: TokenCounts | null;
  onDuration: (seconds: number) => void;
  onClose: () => void;
  onEdit: () => void;
  onShowUsage: () => void;
}) {
  const { t } = useLocale();
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      labelledBy={TITLE_ID}
      className="export-result-dialog"
    >
      <div data-slot="result-card" className="export-result">
        <ResultPlayer artifactId={artifactId} estimateSeconds={seconds} onDuration={onDuration} />
        <div className="export-result__side">
          <div className="export-result__head">
            <h2 id={TITLE_ID} className="export-result__title">
              {t('export.card.doneTitle')}
            </h2>
            <DialogClose
              render={<CloseButton label={t('export.card.close')} className="focus-ring--inset" />}
            />
          </div>
          <p className="export-result__description">{t('export.card.description')}</p>
          <ResultFacts
            view={view}
            seconds={seconds}
            exact={exact}
            tokens={tokens}
            onShowUsage={onShowUsage}
            captionSave
          />
          <div className="export-result__actions">
            <Button variant="secondary" onClick={onEdit}>
              {t('export.toEdit')}
            </Button>
            <Button onClick={() => startDownload(downloadUrl(view.video.id, 'mp4'))}>
              {t('export.save.mp4')}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
