import { useState } from 'react';

import { Button } from '@/components/Button/Button';
import { useLocale } from '@/shared/lib/i18n/locale';

import { useEdit } from './edit-context';
import { SceneConfirm } from './scene-confirm';

/**
 * The edit stage confirms the scenes before handing off to the making. While
 * the voice models are still downloading the button stays pressable: the job it
 * starts waits in the queue, and the preparing percent stands beside the stop
 * control so the control keeps saying what it stops.
 */
export function EditNextAction({ preparePercent = null }: { preparePercent?: number | null }) {
  const { t } = useLocale();
  const edit = useEdit();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const running = edit.phase === 'video';
  const busy = edit.phase === 'stills';

  return (
    <>
      {running && preparePercent !== null ? (
        <span
          data-slot="prepare-percent"
          role="status"
          className="shrink-0 text-[13px] whitespace-nowrap text-[var(--text-muted)]"
        >
          {t('shell.prepare.label', { percent: preparePercent })}
        </span>
      ) : null}
      <Button
        data-slot="next-action"
        className="min-w-[calc(var(--space-48)*3)] shrink-0 px-4 whitespace-nowrap"
        running={running}
        stopLabel={t('edit.next.stop')}
        onStop={edit.stopVideo}
        disabled={!running && (!edit.canStartVideo || edit.busy || busy)}
        onClick={() => setConfirmOpen(true)}
      >
        {t('edit.next.make')}
      </Button>
      <SceneConfirm
        edit={edit}
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onStart={() => {
          setConfirmOpen(false);
          edit.confirmForOutput();
        }}
      />
    </>
  );
}
