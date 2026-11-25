import { createContext, useContext, type ReactNode } from 'react';

import { useEditOptional } from '@/features/edit/edit-context';
import { PrepareNotice } from '@/features/runtime/prepare-notice';
import { usePrepare, type PrepareStatus } from '@/features/runtime/use-prepare';

const EditPrepareContext = createContext<PrepareStatus | null>(null);

/**
 * One reading of the voice models for the edit step. The top bar's make-video
 * button shows its percent and the notice row under the bar says why it cannot
 * move, so both read the same status without polling twice.
 */
export function EditPrepareProvider({ active, children }: { active: boolean; children: ReactNode }) {
  const edit = useEditOptional();
  const prepare = usePrepare(active ? edit?.video?.settings.language ?? null : null);
  return <EditPrepareContext.Provider value={prepare}>{children}</EditPrepareContext.Provider>;
}

export function useEditPrepare(): PrepareStatus {
  const prepare = useContext(EditPrepareContext);
  if (prepare === null) throw new Error('useEditPrepare needs EditPrepareProvider');
  return prepare;
}

/**
 * The sentence for a download that cannot move, in its own row under the top
 * bar: it pushes the work area down instead of floating over its tabs.
 */
export function EditPrepareNotice() {
  return <PrepareNotice status={useEditPrepare()} className="flex justify-end px-4 pb-2" />;
}
