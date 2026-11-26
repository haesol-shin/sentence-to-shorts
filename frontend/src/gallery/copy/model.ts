import { isCopyNamespace } from './rules';

import { isRecord } from './guard';

export type CopyUsage = { path: string; line: number };

/** One gallery case that renders the key, with the title and first label derived from it. */
export type CopyCase = { partId: string; title: string; label: string };

export type CopyEntry = {
  key: string;
  ko: string;
  en: string;
  usages: CopyUsage[];
  cases: CopyCase[];
};

export type CopyFileIndex = {
  namespace: string;
  koKeys: string[];
  enKeys: string[];
  /** SHA-256 of each file as the page loaded it, for the save's stale-page check. */
  koHash: string;
  enHash: string;
  entries: CopyEntry[];
};

export type CopyIndex = {
  editable: boolean;
  files: CopyFileIndex[];
};

/** What a preview frame receives: one edited key and both drafts, with the shown language. */
export type CopyPreview = {
  key: string;
  ko: string;
  en: string;
  language: 'ko' | 'en';
};

function stringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const strings: string[] = [];
  for (const item of value) {
    if (typeof item !== 'string') return null;
    strings.push(item);
  }
  return strings;
}

function parseUsage(value: unknown): CopyUsage | null {
  if (!isRecord(value) || typeof value.path !== 'string' || typeof value.line !== 'number') {
    return null;
  }
  if (!Number.isInteger(value.line) || value.line < 1) return null;
  return { path: value.path, line: value.line };
}

function parseCase(value: unknown): CopyCase | null {
  if (
    !isRecord(value) ||
    typeof value.partId !== 'string' ||
    typeof value.title !== 'string' ||
    typeof value.label !== 'string' ||
    value.label === ''
  ) {
    return null;
  }
  return { partId: value.partId, title: value.title, label: value.label };
}

function parseEntry(value: unknown): CopyEntry | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.key !== 'string' ||
    value.key === '' ||
    typeof value.ko !== 'string' ||
    typeof value.en !== 'string' ||
    !Array.isArray(value.usages) ||
    !Array.isArray(value.cases)
  ) {
    return null;
  }
  const usages: CopyUsage[] = [];
  for (const usage of value.usages) {
    const parsed = parseUsage(usage);
    if (parsed === null) return null;
    usages.push(parsed);
  }
  const cases: CopyCase[] = [];
  for (const item of value.cases) {
    const parsed = parseCase(item);
    if (parsed === null) return null;
    cases.push(parsed);
  }
  return { key: value.key, ko: value.ko, en: value.en, usages, cases };
}

function parseFile(value: unknown): CopyFileIndex | null {
  if (!isRecord(value) || typeof value.namespace !== 'string') return null;
  if (!isCopyNamespace(value.namespace)) return null;
  const koKeys = stringList(value.koKeys);
  const enKeys = stringList(value.enKeys);
  if (koKeys === null || enKeys === null || !Array.isArray(value.entries)) return null;
  if (typeof value.koHash !== 'string' || typeof value.enHash !== 'string') return null;
  const entries: CopyEntry[] = [];
  for (const item of value.entries) {
    const parsed = parseEntry(item);
    if (parsed === null) return null;
    entries.push(parsed);
  }
  return {
    namespace: value.namespace,
    koKeys,
    enKeys,
    koHash: value.koHash,
    enHash: value.enHash,
    entries,
  };
}

/** Reads the server or build index. Returns null for a malformed body. */
export function parseCopyIndex(value: unknown): CopyIndex | null {
  if (!isRecord(value) || typeof value.editable !== 'boolean' || !Array.isArray(value.files)) {
    return null;
  }
  const files: CopyFileIndex[] = [];
  for (const item of value.files) {
    const parsed = parseFile(item);
    if (parsed === null) return null;
    files.push(parsed);
  }
  return { editable: value.editable, files };
}
