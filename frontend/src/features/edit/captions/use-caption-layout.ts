import { useEffect, useRef, useState } from 'react';

import type { CaptionLayout } from '../api';
import type { EditCaption } from '../edit-context';

export interface CaptionLayoutState {
  layout: CaptionLayout | null;
  failed: boolean;
}

/**
 * Read the server's sizing and safe-area checks again when the revision changes.
 */
export function useCaptionLayout(
  caption: EditCaption,
  revision: number | null,
): CaptionLayoutState {
  const [state, setState] = useState<CaptionLayoutState>({ layout: null, failed: false });
  const source = useRef(caption);
  source.current = caption;

  useEffect(() => {
    if (revision === null) return;
    let current = true;
    source.current
      .layout({ font: null, extraLanguage: null, extraFont: null })
      .then((layout) => {
        if (current) setState({ layout, failed: false });
      })
      .catch(() => {
        if (current) setState({ layout: null, failed: true });
      });
    return () => {
      current = false;
    };
  }, [revision]);

  return state;
}
