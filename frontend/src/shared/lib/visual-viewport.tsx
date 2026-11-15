import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

/** A smaller inset than this is a URL bar change, not an opened keyboard. */
const KEYBOARD_MIN_INSET = 120;

export interface ViewportInsets {
  keyboardOpen: boolean;
  inset: number;
}

const CLOSED: ViewportInsets = { keyboardOpen: false, inset: 0 };

const ViewportContext = createContext<ViewportInsets>(CLOSED);

/**
 * The height the keyboard covers. `interactive-widget=resizes-content` already
 * shrinks the layout viewport on browsers that honour it; elsewhere the visual
 * viewport keeps its size and this inset moves the composer above the keys.
 */
export function measureKeyboardInset(
  innerHeight: number,
  viewport: { height: number; offsetTop: number },
): number {
  return Math.max(0, Math.round(innerHeight - viewport.height - viewport.offsetTop));
}

export function VisualViewportProvider({ children }: { children: ReactNode }) {
  const [insets, setInsets] = useState<ViewportInsets>(CLOSED);

  useEffect(() => {
    const viewport = window.visualViewport;
    if (viewport === null || viewport === undefined) {
      return;
    }

    const measure = () => {
      const inset = measureKeyboardInset(window.innerHeight, viewport);
      setInsets({ keyboardOpen: inset > KEYBOARD_MIN_INSET, inset });
    };

    viewport.addEventListener('resize', measure);
    viewport.addEventListener('scroll', measure);
    measure();

    return () => {
      viewport.removeEventListener('resize', measure);
      viewport.removeEventListener('scroll', measure);
    };
  }, []);

  return <ViewportContext.Provider value={insets}>{children}</ViewportContext.Provider>;
}

export function useViewportInsets(): ViewportInsets {
  return useContext(ViewportContext);
}
