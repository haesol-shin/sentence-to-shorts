import type { Language } from '@/shared/api/client';

export const LANGUAGES: readonly Language[] = ['ko', 'en'];

type Entries = Record<string, string>;
type Namespaces = Record<string, Entries>;

const FILES = import.meta.glob('../../../locales/*/*.json', { eager: true }) as Record<
  string,
  { default: unknown }
>;

const FILE_PATH = /\/(ko|en)\/([a-z]+)\.json$/u;

function readEntries(value: unknown): Entries {
  if (typeof value !== 'object' || value === null) {
    return {};
  }
  const entries: Entries = {};
  for (const [key, text] of Object.entries(value as Record<string, unknown>)) {
    if (typeof text === 'string') {
      entries[key] = text;
    }
  }
  return entries;
}

function buildCatalog(): Record<Language, Namespaces> {
  const catalog: Record<Language, Namespaces> = { ko: {}, en: {} };
  for (const [path, module] of Object.entries(FILES)) {
    const match = FILE_PATH.exec(path);
    if (match === null) {
      continue;
    }
    const language = match[1] as Language;
    const namespace = match[2];
    catalog[language][namespace] = readEntries(module.default);
  }
  return catalog;
}

const catalog = buildCatalog();

function interpolate(text: string, vars: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/gu, (whole, name: string) =>
    Object.hasOwn(vars, name) ? String(vars[name]) : whole,
  );
}

/**
 * Looks a key up in `<language>/<namespace>.json`. A key nothing defines stays
 * visible as itself, and Korean answers before the key, so a missing English
 * entry never blank out a screen.
 */
export function translate(
  language: Language,
  key: string,
  vars?: Record<string, string | number>,
): string {
  const dot = key.indexOf('.');
  if (dot < 0) {
    return key;
  }
  const namespace = key.slice(0, dot);
  const entryKey = key.slice(dot + 1);
  const text =
    catalog[language][namespace]?.[entryKey] ??
    catalog.ko[namespace]?.[entryKey] ??
    key;
  return vars === undefined ? text : interpolate(text, vars);
}

/** Every key a language defines, as `namespace.key`, for the catalogue test. */
export function catalogKeys(language: Language): string[] {
  const keys: string[] = [];
  for (const [namespace, entries] of Object.entries(catalog[language])) {
    for (const entryKey of Object.keys(entries)) {
      keys.push(`${namespace}.${entryKey}`);
    }
  }
  return keys.sort();
}

export function catalogNamespaces(language: Language): string[] {
  return Object.keys(catalog[language]).sort();
}
