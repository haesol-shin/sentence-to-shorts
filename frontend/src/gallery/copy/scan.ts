/**
 * Static scans behind the 「문구」 view.
 *
 * Nothing here reads the DOM or the file system: the index builder feeds source
 * text, so the same functions run in the dev server, a build and unit tests.
 *
 * The usage scan finds `t('namespace.key')` calls, template prefixes such as
 * `t(`shell.stage.${stage}`)` and, when the caller supplies the known keys, a
 * key written as a string anywhere in the source. The last form catches values
 * declared as `labelKey: 'shell.nav.newVideo'` and consumed later.
 *
 * The case map in `case-map.ts` records the exact case that renders a key. A
 * key is previewable only when that map names it, so sharing a component is not
 * enough to attach an unrelated case.
 */

import { COPY_NAMESPACE_IDS } from './rules';

export type SourceText = {
  /** A path relative to `frontend/`, for example `src/app/shell/sidebar.tsx`. */
  path: string;
  text: string;
};

export type CopyUsage = {
  path: string;
  line: number;
};

export type CopyScan = {
  /** Literal keys and the places that name them. */
  literals: Map<string, CopyUsage[]>;
  /** Template prefixes, such as `shell.stage.`, with the place that builds them. */
  templates: { prefix: string; usage: CopyUsage }[];
};

const NAMESPACES = COPY_NAMESPACE_IDS.join('|');
const LITERAL_CALL = new RegExp(`\\bt\\(\\s*(['"])((?:${NAMESPACES})\\.[^'"\\n]+)\\1`, 'gu');
const TEMPLATE_CALL = new RegExp('\\bt\\(\\s*`((?:' + NAMESPACES + ')\\.[^`$\\n]*)`', 'gu');
const TEMPLATE_PREFIX = new RegExp(
  '\\bt\\(\\s*`((?:' + NAMESPACES + ')\\.[^`$\\n]*)\\$\\{',
  'gu',
);
const QUOTED = /(['"`])([a-z][A-Za-z0-9_.-]+)\1/gu;

function push(map: Map<string, CopyUsage[]>, key: string, usage: CopyUsage): void {
  const list = map.get(key) ?? [];
  if (!list.some((item) => item.path === usage.path && item.line === usage.line)) {
    list.push(usage);
    map.set(key, list);
  }
}

/** Every reference to a known key in the given sources, grouped by key. */
export function scanCopyUsages(
  sources: readonly SourceText[],
  knownKeys?: ReadonlySet<string>,
): CopyScan {
  const literals = new Map<string, CopyUsage[]>();
  const templates: { prefix: string; usage: CopyUsage }[] = [];
  for (const source of sources) {
    if (!/\.(?:ts|tsx)$/u.test(source.path)) continue;
    const lines = source.text.split('\n');
    lines.forEach((text, index) => {
      const usage = { path: source.path, line: index + 1 };
      for (const match of text.matchAll(LITERAL_CALL)) push(literals, match[2], usage);
      for (const match of text.matchAll(TEMPLATE_CALL)) push(literals, match[1], usage);
      for (const match of text.matchAll(TEMPLATE_PREFIX)) {
        const prefix = match[1];
        if (
          !templates.some(
            (item) =>
              item.prefix === prefix &&
              item.usage.path === usage.path &&
              item.usage.line === usage.line,
          )
        ) {
          templates.push({ prefix, usage });
        }
      }
      if (knownKeys !== undefined) {
        for (const match of text.matchAll(QUOTED)) {
          if (knownKeys.has(match[2])) push(literals, match[2], usage);
        }
      }
    });
  }
  return { literals, templates };
}

/** The places that use one key, sorted by path and line. */
export function usagesOf(scan: CopyScan, key: string): CopyUsage[] {
  const results: CopyUsage[] = [...(scan.literals.get(key) ?? [])];
  for (const { prefix, usage } of scan.templates) {
    if (key.startsWith(prefix)) {
      if (!results.some((item) => item.path === usage.path && item.line === usage.line)) {
        results.push(usage);
      }
    }
  }
  return results.sort((a, b) => a.path.localeCompare(b.path) || a.line - b.line);
}
