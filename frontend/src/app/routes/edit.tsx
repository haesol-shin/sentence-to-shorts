import { Plus } from 'lucide-react';

import { useLocale } from '@/shared/lib/i18n/locale';
import { useStageScrolled } from '@/shared/lib/stage-scroll';
import { cn } from '@/shared/lib/utils';
import { useViewportInsets } from '@/shared/lib/visual-viewport';
import { IconButton } from '@/shared/ui/icon-button';
import { VideoFrame } from '@/shared/ui/video-frame';

/** The scene frames: their own column, grey, scrolling inside itself. */
function SceneColumn() {
  const { t } = useLocale();
  return (
    <div
      data-slot="scene-column"
      className="hidden w-[var(--layout-scene-col-w)] shrink-0 flex-col gap-2 overflow-y-auto bg-[var(--surface-muted)] p-2 md:flex"
    >
      <h2 className="px-1 text-[15px] font-bold text-[var(--text-strong)]">
        {t('shell.edit.frames')}
      </h2>
      <p className="px-1 text-[15px] text-[var(--text-muted)]">{t('shell.edit.framesEmpty')}</p>
      <div className="mt-auto flex justify-center">
        <IconButton label={t('shell.edit.addScene')}>
          <Plus aria-hidden size={20} />
        </IconButton>
      </div>
    </div>
  );
}

/** The same frames on a phone: one row that scrolls sideways. */
function SceneStrip() {
  const { t } = useLocale();
  return (
    <div
      data-slot="scene-strip"
      aria-label={t('shell.edit.frames')}
      className="flex w-full shrink-0 items-center gap-2 overflow-x-auto p-2 md:hidden"
    >
      <p className="shrink-0 px-1 text-[15px] text-[var(--text-muted)]">
        {t('shell.edit.framesEmpty')}
      </p>
      <IconButton label={t('shell.edit.addScene')} className="shrink-0">
        <Plus aria-hidden size={20} />
      </IconButton>
    </div>
  );
}

/**
 * The edit step: conversation, scene frames, preview and the scene panel on one
 * white surface. Only the frames column is grey and no rule or shadow divides
 * them (SPEC 10a.2). On a phone the frames become a row under the preview, and
 * the preview folds into a thumbnail once the keyboard is up or the reader has
 * scrolled away from the top.
 */
export function EditRoute() {
  const { t } = useLocale();
  const { keyboardOpen } = useViewportInsets();
  const scrolled = useStageScrolled();
  const collapsed = keyboardOpen || scrolled;

  return (
    <div data-slot="edit-stage" className="flex min-h-full flex-col md:flex-row">
      <SceneColumn />
      <div
        data-slot="preview"
        data-collapsed={collapsed ? 'true' : undefined}
        className={cn(
          'flex shrink-0 flex-col items-center md:min-h-0 md:flex-1 md:justify-center md:p-4',
          // The thumbnail keeps its note when it folds for a scroll, but the
          // keys leave a phone only the height of the step, the panel and the
          // dock, so the note and the padding give up their room.
          keyboardOpen ? 'gap-0 p-2' : 'gap-2 p-3',
        )}
      >
        <div className="flex w-full items-center justify-center md:min-h-0 md:flex-1">
          <VideoFrame
            className={
              collapsed
                ? 'h-[var(--layout-thumb-h)] w-auto md:h-full'
                : 'h-[var(--layout-mobile-preview-h)] w-auto md:h-full'
            }
          />
        </div>
        <p
          className={cn(
            'text-center text-[15px] text-[var(--text-muted)]',
            keyboardOpen && 'hidden',
          )}
        >
          {t('shell.edit.previewNote')}
        </p>
      </div>
      <SceneStrip />
      <section
        data-slot="stage-panel"
        data-stage="edit"
        aria-label={t('shell.edit.panel')}
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4 md:max-w-[var(--layout-scene-panel-max-w)] md:flex-none md:basis-[var(--layout-scene-panel-max-w)]"
      >
        <h2 className="text-[22px] font-bold text-[var(--text-strong)]">{t('shell.edit.panel')}</h2>
        <p className="text-[15px] text-[var(--text-muted)]">{t('shell.placeholder.empty')}</p>
      </section>
    </div>
  );
}
