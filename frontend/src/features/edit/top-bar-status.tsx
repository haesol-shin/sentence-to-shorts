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
        className={open ? 'max-w-64 top-bar-status__trigger--open' : 'max-w-64'}
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
              className="pointer-events-auto relative flex max-h-[calc(100dvh-var(--layout-topbar-h)-32px)] w-[480px] max-w-[calc(100vw-32px)] flex-col overflow-hidden rounded-[var(--radius-surface)] bg-[var(--popover)] p-6 shadow-[var(--shadow-float)] outline-none"
            >
              {/* Inside the window progress is drawn in the foreground; only the top bar item is blue. */}
              <div className="flex h-[var(--size-control)] items-center justify-between gap-3">
                <DialogPrimitive.Title className="flex items-center gap-[10px] text-[length:var(--font-size-title)] leading-[var(--line-height-body)] font-bold text-[var(--text-strong)]">
                  {edit.phase === 'done' ? (
                    <Check aria-hidden className="size-[var(--icon-title)] text-[var(--foreground)]" />
                  ) : (
                    <span className="spinner text-[var(--foreground)] [--icon-inline:var(--icon-title)]" aria-hidden="true" />
                  )}
                  {edit.phase === 'done' ? t('edit.status.doneTitle') : t('edit.status.title')}
                </DialogPrimitive.Title>
                <DialogPrimitive.Close
                  render={
                    <CloseButton
                      label={t('edit.status.close')}
                      data-slot="progress-close"
                      onClick={close}
                    />
                  }
                />
              </div>
              <DialogPrimitive.Description className="mt-[10px] text-[length:var(--font-size-body)] leading-[var(--line-height-body)] text-[var(--text-muted)]">
                {t('edit.status.description')}
              </DialogPrimitive.Description>
              <Progress
                className="mt-6"
                value={done}
                max={Math.max(1, edit.progress.total)}
                label={t('edit.status.progressTitle')}
                valueText={`${done} / ${edit.progress.total}`}
              />
              <ScrollPane label={t('edit.status.progressLabel')} jumpLabel={t('shell.scroll.jump')} className="mt-4 max-h-80">
                <ul className="flex flex-col gap-3">
                {edit.progress.scenes.map((scene, index) => (
                  <li
                    key={scene.id}
                    data-slot="progress-scene"
                    data-state={scene.state}
                    className="flex h-5 items-center gap-[10px] text-[15px] leading-[18px]"
                  >
                    <span className="inline-flex size-[var(--icon-default)] shrink-0 items-center justify-center" aria-hidden="true">
                      {scene.state === 'done' ? (
                        <Check className="size-[var(--icon-default)] text-[var(--foreground)]" />
                      ) : scene.state === 'running' ? (
                        <span className="spinner text-[var(--foreground)] [--icon-inline:var(--icon-default)]" />
                      ) : (
                        <Clock className="size-[var(--icon-default)] text-[var(--sub)]" />
                      )}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[var(--text-muted)]">
                      {t('edit.scene.number', { number: index + 1 })}
                      {edit.scenes[index] === undefined ? null : ` · ${edit.scenes[index].beat_label}`}
                    </span>
                    <span
                      className={
                        scene.state === 'waiting'
                          ? 'shrink-0 text-[var(--text-muted)]'
                          : 'shrink-0 text-[var(--foreground)]'
                      }
                    >
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
