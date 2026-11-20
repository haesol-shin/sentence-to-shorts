import { useEffect, useRef, useState } from 'react';

import type { CaptionLayout, PinnedRef } from '../api';
import type { EditCaption } from '../edit-context';

export interface CaptionLayoutState {
  layout: CaptionLayout | null;
  failed: boolean;
}

/**
 * The server's layout answer for the trial values, read again when they or the
 * saved revision change. The screen shows the answer and never recomputes it.
 */
export function useCaptionLayout(
  caption: EditCaption,
  trial: { extraLanguage: string | null; extraFont: PinnedRef | null },
  revision: number | null,
): CaptionLayoutState {
  const [state, setState] = useState<CaptionLayoutState>({ layout: null, failed: false });
  const source = useRef(caption);
  source.current = caption;
  const { extraLanguage, extraFont } = trial;
  const fontId = extraFont?.id ?? null;
  const fontRevision = extraFont?.revision ?? null;

  useEffect(() => {
    if (revision === null) return;
    let current = true;
    const font = fontId === null || fontRevision === null ? null : { id: fontId, revision: fontRevision };
    source.current
      .layout({ font: null, extraLanguage, extraFont: extraLanguage === null ? null : font })
      .then((layout) => {
        if (current) setState({ layout, failed: false });
      })
      .catch(() => {
        if (current) setState({ layout: null, failed: true });
      });
    return () => {
      current = false;
    };
  }, [extraLanguage, fontId, fontRevision, revision]);

  return state;
}
