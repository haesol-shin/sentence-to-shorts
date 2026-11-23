import { Redo2, Undo2 } from 'lucide-react';

import { IconButton } from '@/components/IconButton/IconButton';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { useEditOptional } from '@/features/edit/edit-context';
import { undo as undoScript, useScript } from '@/features/script/store';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { View } from './shell-config';

/**
 * Undo and redo at the left of the top bar. They act on the step in front: the
 * script keeps its last change, the edit step keeps the revision before the
 * last change. Redo stays shut with its reason, because a change is undone one
 * step and an undo is not undone again.
 */
export function HistoryButtons({ view }: { view: View }) {
  const { t } = useLocale();
  const edit = useEditOptional();
  const script = useScript();

  const run =
    view === 'edit' && edit !== null
      ? { enabled: edit.canUndo && !edit.busy && !edit.settingsBusy, act: edit.undo }
      : view === 'script' && script !== null
        ? { enabled: script.canUndo, act: undoScript }
        : { enabled: false, act: () => undefined };

  return (
    <div data-slot="history" className="flex shrink-0 items-center">
      <IconButton label={t('edit.history.undo')} disabled={!run.enabled} onClick={run.act}>
        <Undo2 aria-hidden size={20} />
      </IconButton>
      <Tooltip content={t('edit.history.redoReason')} side="bottom">
        <span tabIndex={0} className="inline-flex" data-slot="redo-seat">
          <IconButton label={t('edit.history.redo')} disabled>
            <Redo2 aria-hidden size={20} />
          </IconButton>
        </span>
      </Tooltip>
    </div>
  );
}
