import { useState } from 'react';

import { Button } from '@/components/Button/Button';
import { useLocale } from '@/shared/lib/i18n/locale';

import { useEdit } from './edit-context';
import { SceneConfirm } from './scene-confirm';

/** The edit stage confirms the scenes before handing off to the export check. */
export function EditNextAction() {
  const { t } = useLocale();
  const edit = useEdit();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const running = edit.phase === 'video';
  const busy = edit.phase === 'stills';

  return (
    <>
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
