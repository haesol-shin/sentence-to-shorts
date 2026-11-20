import { Button } from '@/components/Button/Button';
import { Dialog } from '@/components/Dialog/Dialog';
import { Progress } from '@/components/Progress/Progress';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { EditValue } from './edit-context';

export function StillBuild({ edit }: { edit: EditValue }) {
  const { t } = useLocale();
  const open = edit.phase === 'stills';
  const total = edit.stills.total;
  const done = Math.min(edit.stills.done, total);

  return (
    <Dialog
      open={open}
      onOpenChange={() => undefined}
      title={
        <span className="flex items-center gap-2">
          <span className="spinner text-[var(--progress)]" aria-hidden="true" />
          {t('edit.stills.title')}
        </span>
      }
      description={t('edit.stills.description')}
      label={t('edit.stills.title')}
      actions={
        <Button variant="ghost" onClick={edit.cancelStills}>
          {t('edit.stills.cancel')}
        </Button>
      }
    >
      <Progress
        value={done}
        max={Math.max(1, total)}
        label={t('edit.stills.progressLabel')}
        valueText={`${done} / ${total}`}
      />
    </Dialog>
  );
}
