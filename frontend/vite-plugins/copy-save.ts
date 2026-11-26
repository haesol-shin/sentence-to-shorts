/**
 * Dev-only save endpoint for the gallery's 「문구」 view.
 *
 * The endpoint exists only while `vite dev` runs with the local edit mode, and
 * only a loopback request from an origin the server was opened on may write.
 * One save at a time is serialized per namespace across processes by a short
 * lock under `.local`; after the temp files are written, the server re-reads
 * both files and compares hashes before the atomic renames, so an edit made
 * while the save is preparing is reported instead of being overwritten.
 */

import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import type { ServerResponse } from 'node:http';
import { join } from 'node:path';

import type { Plugin, ViteDevServer } from 'vite';

import { isRecord } from '../src/gallery/copy/guard';
import {
  checkCopy,
  isCopyNamespace,
  localeFileName,
  type CopyError,
  type CopyNamespace,
} from '../src/gallery/copy/rules';
import {
  approvedOrigins,
  canWriteCopy,
  serverAddressOf,
} from './request-guard';

const ENDPOINT = '/__copy/save';
const MAX_BODY = 128 * 1024;
const LOCK_WAIT_MS = 3000;
const LOCK_RETRY_MS = 25;

export type CopySaveRequest = {
  namespace: string;
  key: string;
  ko: string;
  en: string;
  /** The values the editor opened with, for a stale-write check. */
  baseKo: string;
  baseEn: string;
  /** SHA-256 of each file as the page loaded it, for the stale-page check. */
  baseHashKo: string;
  baseHashEn: string;
};

export type CopySaveResult =
  | { ok: true; ko: string; en: string; koHash: string; enHash: string }
  | {
      ok: false;
      errors: CopyError[];
      ko?: string;
      en?: string;
      koHash?: string;
      enHash?: string;
    };

export type CopyFileOps = {
  readFile(path: string, encoding: 'utf8'): Promise<string>;
  writeFile(path: string, data: string, encoding: 'utf8'): Promise<void>;
  rename(from: string, to: string): Promise<void>;
  rm(path: string, options: { force: boolean }): Promise<void>;
};

const DEFAULT_OPS: CopyFileOps = { readFile, writeFile, rename, rm };

/** One promise chain per file pair, so a later save in this process reads the earlier result. */
const locks = new Map<string, Promise<unknown>>();

function withNamespaceLock<T>(key: string, task: () => Promise<T>): Promise<T> {
  const previous = locks.get(key) ?? Promise.resolve();
  const next = previous.catch(() => undefined).then(task);
  locks.set(key, next);
  return next.finally(() => {
    if (locks.get(key) === next) locks.delete(key);
  });
}

function requestError(message: string, code: CopyError['code'] = 'request'): CopySaveResult {
  return { ok: false, errors: [{ code, message }] };
}

function conflictResult(
  message: string,
  ko: string,
  en: string,
  koHash: string,
  enHash: string,
): CopySaveResult {
  return { ok: false, errors: [{ code: 'conflict', message }], ko, en, koHash, enHash };
}

function currentValues(
  koText: string,
  enText: string,
  key: string,
): { ko: string; en: string } | null {
  try {
    const ko = JSON.parse(koText) as unknown;
    const en = JSON.parse(enText) as unknown;
    if (!isRecord(ko) || !isRecord(en)) return null;
    const koValue = ko[key];
    const enValue = en[key];
    if (typeof koValue !== 'string' || typeof enValue !== 'string') return null;
    return { ko: koValue, en: enValue };
  } catch {
    return null;
  }
}

function serialize(document: Record<string, unknown>, original: string): string {
  return `${JSON.stringify(document, null, 2)}${original.endsWith('\n') ? '\n' : ''}`;
}

function hashText(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

function tempPath(path: string): string {
  return `${path}.copy-${randomUUID()}.tmp`;
}

async function cleanupTemps(paths: readonly string[], ops: CopyFileOps): Promise<void> {
  await Promise.allSettled(paths.map((path) => ops.rm(path, { force: true })));
}

async function writeAtomic(path: string, content: string, ops: CopyFileOps): Promise<void> {
  const temp = tempPath(path);
  try {
    await ops.writeFile(temp, content, 'utf8');
    await ops.rename(temp, path);
  } catch (error) {
    await cleanupTemps([temp], ops);
    throw error;
  }
}

function lockPathOf(lockDir: string, namespace: CopyNamespace): string {
  return join(lockDir, `copy-${namespace}.lock`);
}

function isLivePid(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'EPERM';
  }
}

async function readLockPid(lockPath: string): Promise<number | null> {
  try {
    const raw = await readFile(join(lockPath, 'pid'), 'utf8');
    const pid = Number(raw.trim());
    return Number.isInteger(pid) && pid > 0 ? pid : null;
  } catch {
    return null;
  }
}

async function tryAcquire(lockDir: string, namespace: CopyNamespace): Promise<boolean> {
  const lockPath = lockPathOf(lockDir, namespace);
  try {
    await mkdir(lockPath);
    try {
      await writeFile(join(lockPath, 'pid'), String(process.pid), 'utf8');
      return true;
    } catch (error) {
      await rm(lockPath, { recursive: true, force: true });
      throw error;
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') return false;
  }
  const pid = await readLockPid(lockPath);
  if (pid === null) return false;
  if (isLivePid(pid)) return false;
  await rm(lockPath, { recursive: true, force: true });
  return false;
}

async function withFileLock<T>(
  lockDir: string,
  namespace: CopyNamespace,
  task: () => Promise<T>,
): Promise<T | null> {
  await mkdir(lockDir, { recursive: true });
  const deadline = Date.now() + LOCK_WAIT_MS;
  for (;;) {
    if (await tryAcquire(lockDir, namespace)) {
      try {
        return await task();
      } finally {
        await rm(lockPathOf(lockDir, namespace), { recursive: true, force: true });
      }
    }
    if (Date.now() >= deadline) return null;
    await new Promise<void>((resolve) => {
      setTimeout(resolve, LOCK_RETRY_MS);
    });
  }
}

async function saveCopyNow(
  localesDir: string,
  request: CopySaveRequest,
  ops: CopyFileOps,
): Promise<CopySaveResult> {
  const namespace = request.namespace;
  if (!isCopyNamespace(namespace)) return requestError('그 문구 파일이 없어요');
  if (typeof request.key !== 'string' || request.key === '') return requestError('키가 비었어요');
  if (
    typeof request.ko !== 'string' ||
    typeof request.en !== 'string' ||
    typeof request.baseKo !== 'string' ||
    typeof request.baseEn !== 'string'
  ) {
    return requestError('값이 문자열이 아니에요');
  }

  const koPath = join(localesDir, localeFileName('ko', namespace));
  const enPath = join(localesDir, localeFileName('en', namespace));
  let koText: string;
  let enText: string;
  try {
    [koText, enText] = await Promise.all([
      ops.readFile(koPath, 'utf8'),
      ops.readFile(enPath, 'utf8'),
    ]);
  } catch {
    return requestError('문구 파일을 읽지 못했어요');
  }

  let koDoc: Record<string, unknown>;
  let enDoc: Record<string, unknown>;
  try {
    const koValue: unknown = JSON.parse(koText);
    const enValue: unknown = JSON.parse(enText);
    if (!isRecord(koValue) || !isRecord(enValue)) return requestError('문구 파일의 형식이 맞지 않아요');
    koDoc = koValue;
    enDoc = enValue;
  } catch {
    return requestError('문구 파일의 형식이 맞지 않아요');
  }

  if (!Object.hasOwn(koDoc, request.key) || !Object.hasOwn(enDoc, request.key)) {
    return requestError('그 키가 두 파일에 모두 있지 않아요', 'unknown-key');
  }

  const currentKo = koDoc[request.key];
  const currentEn = enDoc[request.key];
  if (typeof currentKo !== 'string' || typeof currentEn !== 'string') {
    return requestError('원래 값이 문자열이 아니에요');
  }

  const koHashNow = hashText(koText);
  const enHashNow = hashText(enText);
  const stalePage =
    request.baseHashKo !== koHashNow || request.baseHashEn !== enHashNow;
  if (stalePage) {
    return conflictResult(
      '문구 파일이 다른 곳에서 바뀌었어요. 새로 고친 뒤 다시 저장해 주세요',
      currentKo,
      currentEn,
      koHashNow,
      enHashNow,
    );
  }

  let nextKo = request.ko;
  let nextEn = request.en;
  if (request.ko === request.baseKo) {
    nextKo = currentKo;
  } else if (currentKo !== request.baseKo) {
    return conflictResult(
      '한국어 값이 다른 곳에서 먼저 바뀌었어요. 새로 고친 뒤 저장해 주세요',
      currentKo,
      currentEn,
      koHashNow,
      enHashNow,
    );
  }
  if (request.en === request.baseEn) {
    nextEn = currentEn;
  } else if (currentEn !== request.baseEn) {
    return conflictResult(
      '영어 값이 다른 곳에서 먼저 바뀌었어요. 새로 고친 뒤 저장해 주세요',
      currentKo,
      currentEn,
      koHashNow,
      enHashNow,
    );
  }

  const errors = checkCopy({
    originalKo: currentKo,
    originalEn: currentEn,
    ko: nextKo,
    en: nextEn,
    koKeys: Object.keys(koDoc),
    enKeys: Object.keys(enDoc),
  });
  if (errors.length > 0) return { ok: false, errors };
  if (nextKo === currentKo && nextEn === currentEn) {
    return { ok: true, ko: currentKo, en: currentEn, koHash: koHashNow, enHash: enHashNow };
  }

  koDoc[request.key] = nextKo;
  enDoc[request.key] = nextEn;
  const koNext = serialize(koDoc, koText);
  const enNext = serialize(enDoc, enText);
  const koTemp = tempPath(koPath);
  const enTemp = tempPath(enPath);

  try {
    await ops.writeFile(koTemp, koNext, 'utf8');
    await ops.writeFile(enTemp, enNext, 'utf8');
    const [koNow, enNow] = await Promise.all([
      ops.readFile(koPath, 'utf8'),
      ops.readFile(enPath, 'utf8'),
    ]);
    if (hashText(koNow) !== koHashNow || hashText(enNow) !== enHashNow) {
      const now = currentValues(koNow, enNow, request.key);
      await cleanupTemps([koTemp, enTemp], ops);
      if (now === null) {
        return requestError('문구 파일이 다른 곳에서 바뀌었어요. 새로 고친 뒤 다시 저장해 주세요', 'conflict');
      }
      return conflictResult(
        '문구 파일이 다른 곳에서 바뀌었어요. 새로 고친 뒤 다시 저장해 주세요',
        now.ko,
        now.en,
        hashText(koNow),
        hashText(enNow),
      );
    }
    await ops.rename(koTemp, koPath);
    try {
      await ops.rename(enTemp, enPath);
    } catch {
      try {
        await writeAtomic(koPath, koText, ops);
      } catch {
        await cleanupTemps([enTemp], ops);
        return requestError('파일 일부만 바뀌었어요. 문구 파일을 확인해 주세요', 'partial');
      }
      await cleanupTemps([enTemp], ops);
      return requestError('저장하지 못했어요. 파일은 그대로예요', 'write');
    }
  } catch {
    await cleanupTemps([koTemp, enTemp], ops);
    return requestError('저장하지 못했어요. 파일은 그대로예요', 'write');
  }

  return {
    ok: true,
    ko: nextKo,
    en: nextEn,
    koHash: hashText(koNext),
    enHash: hashText(enNext),
  };
}

export function saveCopy(
  localesDir: string,
  request: CopySaveRequest,
  options: { lockDir: string; ops?: CopyFileOps },
): Promise<CopySaveResult> {
  const namespace = request.namespace;
  if (!isCopyNamespace(namespace)) {
    return Promise.resolve(requestError('그 문구 파일이 없어요'));
  }
  const lockKey = `${localesDir}\u0000${namespace}`;
  return withNamespaceLock(lockKey, async () => {
    const result = await withFileLock(options.lockDir, namespace, () =>
      saveCopyNow(localesDir, request, options.ops ?? DEFAULT_OPS),
    );
    return result ?? requestError('다른 저장이 진행 중이에요. 잠시 뒤 다시 시도해 주세요', 'conflict');
  });
}

/** Collects the body as bytes, then decodes once so a UTF-8 character may cross chunks. */
export function readBody(req: NodeJS.ReadableStream): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    let stopped = false;
    req.on('data', (chunk: Buffer | string) => {
      if (stopped) return;
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      size += buffer.length;
      if (size > MAX_BODY) {
        stopped = true;
        reject(new Error('too large'));
        return;
      }
      chunks.push(buffer);
    });
    req.on('end', () => {
      if (!stopped) resolve(Buffer.concat(chunks).toString('utf8'));
    });
    req.on('error', (error) => {
      if (!stopped) {
        stopped = true;
        reject(error);
      }
    });
  });
}

function parseRequest(value: unknown): CopySaveRequest | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.namespace !== 'string' ||
    typeof value.key !== 'string' ||
    typeof value.ko !== 'string' ||
    typeof value.en !== 'string' ||
    typeof value.baseKo !== 'string' ||
    typeof value.baseEn !== 'string' ||
    typeof value.baseHashKo !== 'string' ||
    typeof value.baseHashEn !== 'string'
  ) {
    return null;
  }
  return {
    namespace: value.namespace,
    key: value.key,
    ko: value.ko,
    en: value.en,
    baseKo: value.baseKo,
    baseEn: value.baseEn,
    baseHashKo: value.baseHashKo,
    baseHashEn: value.baseHashEn,
  };
}

function reply(server: ViteDevServer, res: ServerResponse, status: number, value: unknown): void {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(value));
  server.config.logger.info(`[copy] save ${status}`);
}

export function copySavePlugin(options?: {
  edit?: boolean;
  localesDir?: string;
  lockDir?: string;
}): Plugin {
  return {
    name: 'gallery-copy-save',
    apply: 'serve',
    configureServer(server) {
      const localesDir = options?.localesDir ?? join(server.config.root, 'src', 'locales');
      const lockDir = options?.lockDir ?? join(server.config.root, '.local');
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? '').split('?')[0];
        if (path !== ENDPOINT) {
          next();
          return;
        }
        const origin = typeof req.headers.origin === 'string' ? req.headers.origin : undefined;
        const host = typeof req.headers.host === 'string' ? req.headers.host : undefined;
        if (
          !canWriteCopy({
            edit: options?.edit === true,
            remoteAddress: req.socket.remoteAddress,
            origin,
            host,
            approvedOrigins: approvedOrigins(serverAddressOf(server)),
          })
        ) {
          reply(server, res, 403, requestError('이 갤러리에서는 저장할 수 없어요', 'forbidden'));
          return;
        }
        if (req.method !== 'POST') {
          reply(server, res, 405, requestError('POST만 받아요'));
          return;
        }
        const contentType = typeof req.headers['content-type'] === 'string' ? req.headers['content-type'] : '';
        if (!contentType.startsWith('application/json')) {
          reply(server, res, 415, requestError('JSON 본문만 받아요'));
          return;
        }
        void readBody(req)
          .then((body) => {
            let parsed: unknown;
            try {
              parsed = JSON.parse(body);
            } catch {
              reply(server, res, 400, requestError('보낸 값이 JSON이 아니에요'));
              return;
            }
            const request = parseRequest(parsed);
            if (request === null) {
              reply(server, res, 400, requestError('보낸 값의 형식이 맞지 않아요'));
              return;
            }
            return saveCopy(localesDir, request, { lockDir })
              .then((result) => {
                const status = result.ok
                  ? 200
                  : result.errors.some((error) => error.code === 'conflict')
                    ? 409
                    : 400;
                reply(server, res, status, result);
              })
              .catch(() => {
                reply(server, res, 500, requestError('저장하지 못했어요. 다시 시도해 주세요'));
              });
          })
          .catch(() => {
            reply(server, res, 413, requestError('보낸 값이 너무 커요'));
          });
      });
    },
  };
}
