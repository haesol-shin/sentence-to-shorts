import { createContext, useContext, useMemo, type ReactNode } from 'react';

import type { Language } from '@/shared/api/client';

import { translate } from './catalog';

export type Translate = (key: string, vars?: Record<string, string | number>) => string;

export interface LocaleValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: Translate;
}

const LocaleContext = createContext<LocaleValue | null>(null);

export function LocaleProvider({
  language,
  setLanguage,
  children,
}: {
  language: Language;
  setLanguage: (language: Language) => void;
  children: ReactNode;
}) {
  const value = useMemo<LocaleValue>(
    () => ({
      language,
      setLanguage,
      t: (key, vars) => translate(language, key, vars),
    }),
    [language, setLanguage],
  );
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleValue {
  const value = useContext(LocaleContext);
  if (value === null) {
    throw new Error('useLocale must be used inside a LocaleProvider');
  }
  return value;
}
