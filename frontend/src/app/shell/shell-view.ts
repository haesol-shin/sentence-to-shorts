import { createContext, useContext } from 'react';

import type { View } from './shell-config';

const ShellViewContext = createContext<View | null>(null);

export const ShellViewProvider = ShellViewContext.Provider;

export function useShellView(): View | null {
  return useContext(ShellViewContext);
}
