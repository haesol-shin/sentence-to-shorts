import type { ReactNode } from 'react';

import { EditProvider } from '@/features/edit/edit-context';

/** The edit provider owns the server video the first screen started. */
export function EditBridge({
  active,
  videoId,
  children,
}: {
  active: boolean;
  videoId: string | null;
  children: ReactNode;
}) {
  return (
    <EditProvider active={active} videoId={videoId}>
      {children}
    </EditProvider>
  );
}
