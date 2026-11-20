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
    <div data-slot="edit-stage" className="flex min-h-full flex-col md:flex-row">
      <SceneColumn edit={edit} />
      <div
        data-slot="preview"
        data-collapsed={collapsed ? 'true' : undefined}
        className={cn(
          'flex min-w-0 shrink-0 flex-col md:min-h-0 md:flex-1 md:shrink md:justify-start md:px-[28px] md:py-4',
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
        className="edit-stage-panel flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-[28px] py-4 md:max-w-[var(--layout-scene-panel-max-w)]"
      >
        <ScenePanel edit={edit} />
      </section>
      <StillBuild edit={edit} />
      <ChangeReview edit={edit} />
    </div>
  );
}
