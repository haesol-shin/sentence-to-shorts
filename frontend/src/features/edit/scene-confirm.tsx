import { createContext, useContext, type ReactNode } from 'react';

import { Button } from '@/components/Button/Button';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Dialog, DialogClose } from '@/components/Dialog/Dialog';
import { Notice } from '@/components/Notice/Notice';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { EditValue } from './edit-context';
import { estimatedSeconds, stillIsReady } from './model';

/**
 * What the shell says about the voice files before the video starts. Only the
 * shell reads the runtime, so it hands the sentence down through this seat.
 */
export const SceneConfirmNoticeContext = createContext<ReactNode>(null);

export function SceneConfirm({
  edit,
  open,
  onOpenChange,
  onStart,
}: {
  edit: EditValue;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStart: () => void;
}) {
  const { t } = useLocale();
  const missing = edit.scenes.filter((scene) => !stillIsReady(edit.build, scene.id)).length;
  const voiceNotice = useContext(SceneConfirmNoticeContext);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('edit.confirm.title')}
      description={t('edit.confirm.description')}
      label={t('edit.confirm.title')}
      actions={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            {t('edit.confirm.cancel')}
          </Button>
          <Button disabled={!edit.canStartVideo || edit.busy || edit.entryPreview} onClick={onStart}>
            {t('edit.confirm.start')}
          </Button>
        </>
      }
    >
      <DialogClose
        render={<CloseButton label={t('edit.preview.close')} className="absolute top-4 right-4" />}
      />
      <div data-slot="scene-confirm" className="flex flex-col gap-3">
        <ol className="flex flex-col gap-1">
          {edit.scenes.map((scene, index) => (
            <li
              key={scene.id}
              className="flex min-h-11 items-center justify-between gap-2 rounded-[var(--radius-row)] bg-[var(--surface-muted)] px-3 text-[15px]"
            >
              <span className="min-w-0 truncate">
                {t('edit.scene.number', { number: index + 1 })} · {scene.beat_label}
              </span>
              <span className="shrink-0 text-[var(--text-muted)]">
                {t('edit.scene.estimated', { seconds: estimatedSeconds(scene) })}
              </span>
            </li>
          ))}
        </ol>
        <div className="flex items-center justify-between gap-2 text-[15px]">
          <span className="font-bold">{t('edit.confirm.total')}</span>
          <span>{t('edit.confirm.totalValue', { seconds: edit.totalSeconds })}</span>
        </div>
        {missing === 0 ? null : (
          <Notice>{t('edit.confirm.missing', { count: missing })}</Notice>
        )}
        {voiceNotice}
        {edit.canStartVideo ? null : <Notice>{t('edit.error.notConfirmed')}</Notice>}
      </div>
    </Dialog>
  );
}
