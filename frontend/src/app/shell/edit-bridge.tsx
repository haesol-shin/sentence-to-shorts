import type { ReactNode } from 'react';

import { EditProvider } from '@/features/edit/edit-context';

/** The edit provider owns the server video the first screen started. */
export function EditBridge({
  active,
  previewOnEntry,
  videoId,
  children,
}: {
  active: boolean;
  previewOnEntry: boolean;
  videoId: string | null;
  children: ReactNode;
}) {
  return (
    <EditProvider active={active} previewOnEntry={previewOnEntry} videoId={videoId}>
      {children}
    </EditProvider>
  );
}
