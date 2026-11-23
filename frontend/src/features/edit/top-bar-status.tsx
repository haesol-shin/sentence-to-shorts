import { useRef, useState } from 'react';
import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { Check, Clock } from 'lucide-react';

import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Progress } from '@/components/Progress/Progress';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { TopBarStatus } from '@/components/TopBarStatus/TopBarStatus';
import { useLocale } from '@/shared/lib/i18n/locale';

import { useEdit } from './edit-context';

/**
 * The 480 progress window is non-modal: its scrim starts under the top bar, so
 * the same top bar can still stop the job while the window stays open.
 */
export function EditTopBarStatus() {
  const { t } = useLocale();
  const edit = useEdit();
  const [open, setOpen] = useState(false);
  const frame = useRef<HTMLDivElement>(null);

  if (edit.phase !== 'video' && edit.phase !== 'done') return null;

  const done = edit.phase === 'done' ? edit.progress.total : edit.progress.done;
  const label =
    edit.phase === 'done'
      ? t('edit.status.done')
      : t('edit.status.making', { done, total: edit.progress.total });
  const close = () => {
    setOpen(false);
    window.requestAnimationFrame(() => {
      frame.current?.querySelector<HTMLButtonElement>('.top-bar-status__trigger')?.focus();
    });
  };

  return (
    <div ref={frame} className="contents">
      <TopBarStatus
        label={label}
        tone={edit.phase === 'done' ? 'saved' : 'working'}
        title={t('edit.status.title')}
        description={t('edit.status.description')}
        open={false}
        onOpenChange={(next) => {
          if (next) setOpen(true);
        }}
        className="max-w-64"
      />
      <DialogPrimitive.Root open={open} onOpenChange={setOpen} modal={false}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Backdrop
            data-slot="progress-scrim"
            className="fixed inset-x-0 top-[var(--layout-topbar-h)] bottom-0 z-[var(--z-panel)] bg-[var(--overlay-dialog-scrim)]"
          />
          <div className="pointer-events-none fixed inset-x-0 top-[var(--layout-topbar-h)] bottom-0 z-[calc(var(--z-panel)+1)] flex items-center justify-center p-4">
            <DialogPrimitive.Popup
              data-slot="progress-window"
              role="dialog"
              aria-label={t('edit.status.title')}
              className="pointer-events-auto relative flex max-h-[calc(100dvh-var(--layout-topbar-h)-32px)] w-[480px] max-w-[calc(100vw-32px)] flex-col gap-4 overflow-hidden rounded-[var(--radius-surface)] bg-[var(--popover)] p-6 shadow-[var(--shadow-float)] outline-none"
            >
              <div className="flex items-start justify-between gap-3">
                <DialogPrimitive.Title className="flex items-center gap-2 text-[22px] leading-[var(--font-size-title)] font-bold text-[var(--text-strong)]">
                  {edit.phase === 'done' ? (
                    <Check aria-hidden className="text-[var(--progress)]" />
                  ) : (
                    <span className="spinner text-[var(--progress)]" aria-hidden="true" />
                  )}
                  {edit.phase === 'done' ? t('edit.status.doneTitle') : t('edit.status.title')}
                </DialogPrimitive.Title>
                <DialogPrimitive.Close
                  render={
                    <CloseButton
                      label={t('edit.status.close')}
                      data-slot="progress-close"
                      className="my-[calc((var(--font-size-title)-var(--size-control))/2)]"
                      onClick={close}
                    />
                  }
                />
              </div>
              <DialogPrimitive.Description className="text-[15px] text-[var(--text-muted)]">
                {t('edit.status.description')}
              </DialogPrimitive.Description>
              <Progress
                value={done}
                max={Math.max(1, edit.progress.total)}
                label={t('edit.status.progressLabel')}
                valueText={`${done} / ${edit.progress.total}`}
              />
              {/* The 44 row leaves 15px under its 15px text; pull the list up so the bottom space reads 24. */}
              <ScrollPane label={t('edit.status.progressLabel')} jumpLabel={t('shell.scroll.jump')} className="max-h-80 -mb-[15px]">
                <ul className="flex flex-col gap-1">
                {edit.progress.scenes.map((scene, index) => (
                  <li
                    key={scene.id}
                    data-slot="progress-scene"
                    data-state={scene.state}
                    className="flex min-h-11 items-center gap-2 text-[15px]"
                  >
                    <span className="inline-flex size-6 shrink-0 items-center justify-center" aria-hidden="true">
                      {scene.state === 'done' ? (
                        <Check className="text-[var(--foreground)]" />
                      ) : scene.state === 'running' ? (
                        <span className="spinner text-[var(--progress)]" />
                      ) : (
                        <Clock className="text-[var(--sub)]" />
                      )}
                    </span>
                    <span className="min-w-0 flex-1 truncate">
                      {t('edit.scene.number', { number: index + 1 })}
                      {edit.scenes[index] === undefined ? null : ` · ${edit.scenes[index].beat_label}`}
                    </span>
                    <span className="shrink-0 text-[13px] text-[var(--text-muted)]">
                      {scene.state === 'done'
                        ? t('edit.status.finished')
                        : scene.state === 'running'
                          ? t('edit.status.working')
                          : t('edit.status.waiting')}
                    </span>
                  </li>
                ))}
                </ul>
              </ScrollPane>
            </DialogPrimitive.Popup>
          </div>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    </div>
  );
}
