import { useEffect, useState } from 'react';

import { messageKeyOf } from '@/shared/api/client';

export interface Loaded<T> {
  data: T | null;
  failureKey: string | null;
  /** True until the read is allowed and has answered. */
  pending: boolean;
}

/**
 * Reads once, and only when `enabled` says the caller may read. The loader
 * must be stable (module scope) so a re-render never fires a second request.
 */
export function useLoad<T>(
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ data: null, failureKey: null, pending: true });

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const controller = new AbortController();
    load(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setState({ data, failureKey: null, pending: false });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ data: null, failureKey: messageKeyOf(error), pending: false });
        }
      });
    return () => controller.abort();
  }, [load, enabled]);

  return state;
}
