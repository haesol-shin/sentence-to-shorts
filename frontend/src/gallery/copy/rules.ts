/**
 * The gallery copy view's one rule module.
 *
 * The app catalog stays untouched: this module is the only source inside the
 * gallery for the namespace list, the locale file pattern, the placeholder
 * syntax and the save checks. The dev server imports it from Node, so it has
 * no browser or React imports.
 */

export const COPY_NAMESPACE_IDS = [
  'shell',
  'concept',
  'script',
  'edit',
  'export',
  'audio',
  'errors',
] as const;

export type CopyNamespace = (typeof COPY_NAMESPACE_IDS)[number];

export type LocaleEntries = Record<string, string>;

export function isCopyNamespace(value: string): value is CopyNamespace {
  return (COPY_NAMESPACE_IDS as readonly string[]).includes(value);
}

/** `ko/<namespace>.json` and `en/<namespace>.json`, the only files the view edits. */
export function localeFileName(language: 'ko' | 'en', namespace: CopyNamespace): string {
  return `${language}/${namespace}.json`;
}

/** Keeps only the string entries, so a malformed value never reaches a check. */
export function readLocaleEntries(value: unknown): LocaleEntries {
  if (typeof value !== 'object' || value === null) return {};
  const entries: LocaleEntries = {};
  for (const [key, text] of Object.entries(value as Record<string, unknown>)) {
    if (typeof text === 'string') entries[key] = text;
  }
  return entries;
}

const PLACEHOLDER_SOURCE = String.raw`\{(\w+)\}`;

function placeholderPattern(): RegExp {
  return new RegExp(PLACEHOLDER_SOURCE, 'gu');
}

/** The placeholder names in a value, in order, without duplicates. */
export function placeholders(text: string): string[] {
  const names: string[] = [];
  for (const match of text.matchAll(placeholderPattern())) {
    if (!names.includes(match[1])) names.push(match[1]);
  }
  return names;
}

/** Fills placeholders with sample values; unknown names stay visible. */
export function interpolateCopy(text: string, vars: Record<string, string | number>): string {
  return text.replace(placeholderPattern(), (whole, name: string) =>
    Object.hasOwn(vars, name) ? String(vars[name]) : whole,
  );
}

export type CopyErrorCode =
  | 'empty-ko'
  | 'empty-en'
  | 'placeholder-ko'
  | 'placeholder-en'
  | 'key-set'
  | 'unknown-key'
  | 'conflict'
  | 'forbidden'
  | 'write'
  | 'partial'
  | 'request';

export type CopyError = {
  code: CopyErrorCode;
  message: string;
};

export type CopyCheckInput = {
  originalKo: string;
  originalEn: string;
  ko: string;
  en: string;
  koKeys: readonly string[];
  enKeys: readonly string[];
};

function missingPlaceholders(original: string, edited: string): string[] {
  const kept = new Set(placeholders(edited));
  return placeholders(original).filter((name) => !kept.has(name));
}

function missingMessage(names: readonly string[]): string {
  if (names.length === 1) return `{${names[0]}}이 빠졌어요`;
  return `빠진 자리표시: ${names.map((name) => `{${name}}`).join(', ')}`;
}

/** Runs every save check on one draft. */
export function checkCopy(input: CopyCheckInput): CopyError[] {
  const errors: CopyError[] = [];
  if (input.ko.trim() === '') {
    errors.push({ code: 'empty-ko', message: '한국어 값이 비었어요' });
  }
  if (input.en.trim() === '') {
    errors.push({ code: 'empty-en', message: '영어 값이 비었어요' });
  }
  const missingKo = input.ko.trim() === '' ? [] : missingPlaceholders(input.originalKo, input.ko);
  if (missingKo.length > 0) {
    errors.push({ code: 'placeholder-ko', message: missingMessage(missingKo) });
  }
  const missingEn = input.en.trim() === '' ? [] : missingPlaceholders(input.originalEn, input.en);
  if (missingEn.length > 0) {
    errors.push({ code: 'placeholder-en', message: `영어 값에 ${missingMessage(missingEn)}` });
  }
  const ko = new Set(input.koKeys);
  const en = new Set(input.enKeys);
  const onlyKo = input.koKeys.filter((key) => !en.has(key));
  const onlyEn = input.enKeys.filter((key) => !ko.has(key));
  if (onlyKo.length > 0 || onlyEn.length > 0) {
    const parts: string[] = [];
    if (onlyKo.length > 0) parts.push(`한국어에만 ${onlyKo.length}개`);
    if (onlyEn.length > 0) parts.push(`영어에만 ${onlyEn.length}개`);
    errors.push({ code: 'key-set', message: `한국어와 영어 파일의 키가 달라요 (${parts.join(', ')})` });
  }
  return errors;
}
