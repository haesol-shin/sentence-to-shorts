/**
 * Builds the copy index once on the server and sends only the index to the
 * browser. The index has every key, its two values, the source lines that name
 * it and the exact gallery case that renders it; the app source itself stays
 * out of the browser.
 */

import { createHash } from 'node:crypto';
import { readdirSync, readFileSync } from 'node:fs';
import type { ServerResponse } from 'node:http';
import { join, relative, sep } from 'node:path';

import type { Plugin, ViteDevServer } from 'vite';

import { COPY_CASES } from '../src/gallery/copy/case-map';
import type { CopyCase, CopyEntry, CopyFileIndex, CopyIndex } from '../src/gallery/copy/model';
import {
  COPY_NAMESPACE_IDS,
  localeFileName,
  readLocaleEntries,
  type CopyNamespace,
  type LocaleEntries,
} from '../src/gallery/copy/rules';
import { scanCopyUsages, usagesOf, type SourceText } from '../src/gallery/copy/scan';
import { galleryParts } from '../src/gallery/items';
import { approvedOrigins, canEditCopy, serverAddressOf } from './request-guard';

const VIRTUAL_ID = 'virtual:copy-index';
const RESOLVED_ID = `\0${VIRTUAL_ID}`;
const ENDPOINT = '/__copy/index';

type LocaleFile = {
  namespace: CopyNamespace;
  ko: LocaleEntries;
  en: LocaleEntries;
  koHash: string;
  enHash: string;
};

function sourceFiles(dir: string, root: string): SourceText[] {
  const found: SourceText[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...sourceFiles(path, root));
      continue;
    }
    if (!/\.(?:ts|tsx)$/u.test(entry.name)) continue;
    found.push({
      path: relative(root, path).split(sep).join('/'),
      text: readFileSync(path, 'utf8'),
    });
  }
  return found.sort((a, b) => a.path.localeCompare(b.path));
}

function readLocaleFile(
  root: string,
  language: 'ko' | 'en',
  namespace: CopyNamespace,
): { entries: LocaleEntries; hash: string } {
  const path = join(root, 'src', 'locales', localeFileName(language, namespace));
  const text = readFileSync(path, 'utf8');
  return {
    entries: readLocaleEntries(JSON.parse(text) as unknown),
    hash: createHash('sha256').update(text).digest('hex'),
  };
}

function localeFiles(root: string): LocaleFile[] {
  return COPY_NAMESPACE_IDS.map((namespace) => {
    const ko = readLocaleFile(root, 'ko', namespace);
    const en = readLocaleFile(root, 'en', namespace);
    return {
      namespace,
      ko: ko.entries,
      en: en.entries,
      koHash: ko.hash,
      enHash: en.hash,
    };
  });
}

function caseFor(key: string): CopyCase[] {
  const spec = COPY_CASES[key];
  if (spec === undefined) return [];
  const part = galleryParts.find((candidate) => candidate.id === spec.partId);
  const entry = part?.cases.find((candidate) => candidate.slug === spec.slug);
  if (part === undefined || entry === undefined) return [];
  return [{ partId: part.id, title: `${part.number}. ${part.title}`, label: entry.label }];
}

/** Reads the locale files and source text, then joins keys to usages and cases. */
export function buildCopyIndex(root: string): CopyIndex {
  const files = localeFiles(root);
  const knownKeys = new Set<string>();
  for (const file of files) {
    for (const key of Object.keys(file.ko)) knownKeys.add(`${file.namespace}.${key}`);
  }
  const sources = sourceFiles(join(root, 'src'), root);
  // Gallery sources define the preview case, not a real app usage.
  const usageSources = sources.filter((source) => !source.path.startsWith('src/gallery/'));
  const scan = scanCopyUsages(usageSources, knownKeys);

  const indexed: CopyFileIndex[] = files.map((file) => {
    const entries: CopyEntry[] = Object.keys(file.ko).map((key) => {
      const full = `${file.namespace}.${key}`;
      return {
        key,
        ko: file.ko[key],
        en: file.en[key] ?? '',
        usages: usagesOf(scan, full),
        cases: caseFor(full),
      };
    });
    return {
      namespace: file.namespace,
      koKeys: Object.keys(file.ko),
      enKeys: Object.keys(file.en),
      koHash: file.koHash,
      enHash: file.enHash,
      entries,
    };
  });
  return { editable: false, files: indexed };
}

function reply(server: ViteDevServer, res: ServerResponse, status: number, value: unknown): void {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(value));
  server.config.logger.info(`[copy] index ${status}`);
}

export function copyIndexPlugin(options?: { edit?: boolean }): Plugin {
  let root = process.cwd();
  return {
    name: 'gallery-copy-index',
    configResolved(config) {
      root = config.root;
    },
    resolveId(id) {
      return id === VIRTUAL_ID ? RESOLVED_ID : null;
    },
    load(id) {
      if (id !== RESOLVED_ID) return null;
      return `export default ${JSON.stringify(buildCopyIndex(root))};`;
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if ((req.url ?? '').split('?')[0] !== ENDPOINT) {
          next();
          return;
        }
        if (req.method !== 'GET') {
          reply(server, res, 405, { error: 'GET만 받아요' });
          return;
        }
        try {
          const index = buildCopyIndex(server.config.root);
          const referer = typeof req.headers.referer === 'string' ? req.headers.referer : undefined;
          const editable = canEditCopy({
            edit: options?.edit === true,
            remoteAddress: req.socket.remoteAddress,
            referer,
            approvedOrigins: approvedOrigins(serverAddressOf(server)),
          });
          reply(server, res, 200, { ...index, editable });
        } catch {
          reply(server, res, 500, { error: '문구 목록을 만들지 못했어요' });
        }
      });
    },
  };
}
