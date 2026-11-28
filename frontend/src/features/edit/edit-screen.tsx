import { useLocale } from '@/shared/lib/i18n/locale';
import { useStageScrolled } from '@/shared/lib/stage-scroll';
import { useViewportInsets } from '@/shared/lib/visual-viewport';
import { cn } from '@/shared/lib/utils';

import { ChangeReview } from './change-review';
import { EMPTY_EDIT_VALUE, useEditOptional } from './edit-context';
import { SceneColumn, SceneStrip } from './scene-column';
import { ScenePanel } from './scene-panel';
import { ScenePreview } from './scene-preview';
import { StillBuild } from './still-build';
import './edit.css';

/**
 * The edit step owns one white surface: the grey scene column, the preview and
 * the scene panel. The conversation stays in the shell, so the chat column and
 * the work area keep the same boundary on every stage.
 */
export function EditScreen() {
  const { t } = useLocale();
  const edit = useEditOptional() ?? EMPTY_EDIT_VALUE;
  const { keyboardOpen } = useViewportInsets();
  const scrolled = useStageScrolled();
  const collapsed = keyboardOpen || scrolled;

  return (
    <div data-slot="edit-stage" className="flex min-h-full flex-col md:h-full md:flex-row">
      <SceneColumn edit={edit} />
      <div
        data-slot="preview"
        data-collapsed={collapsed ? 'true' : undefined}
        className={cn(
          'edit-preview min-w-0 shrink-0 md:min-h-0 md:shrink md:px-[var(--layout-gutter)] md:pt-[26px] md:pb-[var(--layout-gutter)]',
          keyboardOpen ? 'gap-0 p-2' : 'gap-2 p-3',
        )}
      >
        <ScenePreview edit={edit} collapsed={collapsed} />
      </div>
      <SceneStrip edit={edit} />
      <section
        data-slot="stage-panel"
        data-stage="edit"
        aria-label={t('shell.edit.panel')}
        className="edit-stage-panel flex min-h-0 flex-1 flex-col overflow-hidden md:max-w-[var(--layout-scene-panel-max-w)]"
      >
        <ScenePanel edit={edit} />
      </section>
      <StillBuild edit={edit} />
      <ChangeReview edit={edit} />
    </div>
  );
}
