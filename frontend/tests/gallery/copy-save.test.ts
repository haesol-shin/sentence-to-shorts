import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Readable } from 'node:stream';

import { afterEach, describe, expect, test } from 'vitest';

import {
  readBody,
  saveCopy,
  type CopyFileOps,
  type CopySaveRequest,
  type CopySaveResult,
} from '../../vite-plugins/copy-save';
import {
  approvedOrigins,
  canEditCopy,
  canWriteCopy,
  isLoopback,
} from '../../vite-plugins/request-guard';

const roots: string[] = [];
const realOps: CopyFileOps = {
  readFile: async (path, encoding) => readFile(path, encoding),
  writeFile: async (path, data, encoding) => {
    await writeFile(path, data, encoding);
  },
  rename: async (from, to) => {
    await rename(from, to);
  },
  rm: async (path, options) => {
    await rm(path, options);
  },
};

type Fixture = {
  root: string;
  lockDir: string;
  koPath: string;
  enPath: string;
};

async function fixture(ko: Record<string, string>, en: Record<string, string>): Promise<Fixture> {
  const root = await mkdtemp(join(tmpdir(), 'gallery-copy-'));
  roots.push(root);
  await mkdir(join(root, 'ko'));
  await mkdir(join(root, 'en'));
  const koPath = join(root, 'ko', 'shell.json');
  const enPath = join(root, 'en', 'shell.json');
  await writeFile(koPath, `${JSON.stringify(ko, null, 2)}\n`, 'utf8');
  await writeFile(enPath, `${JSON.stringify(en, null, 2)}\n`, 'utf8');
  return { root, lockDir: join(root, '.local'), koPath, enPath };
}

type Draft = Omit<CopySaveRequest, 'baseHashKo' | 'baseHashEn'>;

function sha(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

async function hashesOf(files: Fixture): Promise<{ koHash: string; enHash: string }> {
  const [ko, en] = await Promise.all([
    readFile(files.koPath, 'utf8'),
    readFile(files.enPath, 'utf8'),
  ]);
  return { koHash: sha(ko), enHash: sha(en) };
}

async function save(
  files: Fixture,
  request: Draft,
  ops: CopyFileOps = realOps,
  baseHashes?: { koHash: string; enHash: string },
): Promise<CopySaveResult> {
  const base = baseHashes ?? (await hashesOf(files));
  return saveCopy(
    files.root,
    { ...request, baseHashKo: base.koHash, baseHashEn: base.enHash },
    { lockDir: files.lockDir, ops },
  );
}

function draft(
  key: string,
  ko: string,
  en: string,
  baseKo: string,
  baseEn: string,
): Draft {
  return { namespace: 'shell', key, ko, en, baseKo, baseEn };
}

afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});

describe('copy save endpoint', () => {
  test('test_10a_copy_save_changes_one_line_per_language_and_keeps_order', async () => {
    const files = await fixture(
      { 'a.one': '하나', 'a.two': '파일 {name}을 지워요', 'a.three': '셋' },
      { 'a.one': 'One', 'a.two': 'Remove {name}', 'a.three': 'Three' },
    );
    const koBefore = await readFile(files.koPath, 'utf8');
    const enBefore = await readFile(files.enPath, 'utf8');
    const result = await save(
      files,
      draft(
        'a.two',
        '파일 {name}을 지금 지워요',
        'Remove {name} now',
        '파일 {name}을 지워요',
        'Remove {name}',
      ),
    );
    expect(result).toMatchObject({
      ok: true,
      ko: '파일 {name}을 지금 지워요',
      en: 'Remove {name} now',
    });
    const koAfter = await readFile(files.koPath, 'utf8');
    const enAfter = await readFile(files.enPath, 'utf8');
    expect(Object.keys(JSON.parse(koAfter) as Record<string, string>)).toEqual([
      'a.one',
      'a.two',
      'a.three',
    ]);
    expect(koAfter.startsWith('{\n  "a.one"')).toBe(true);
    expect(koAfter.endsWith('\n')).toBe(true);
    const koChanged = koAfter.split('\n').filter((line, index) => line !== koBefore.split('\n')[index]);
    const enChanged = enAfter.split('\n').filter((line, index) => line !== enBefore.split('\n')[index]);
    expect(koChanged).toEqual(['  "a.two": "파일 {name}을 지금 지워요",']);
    expect(enChanged).toEqual(['  "a.two": "Remove {name} now",']);
  });

  test('test_10a_copy_save_rejects_a_stale_page_before_overwriting_another_key', async () => {
    const files = await fixture({ 'a.one': '하나', 'a.two': '둘' }, { 'a.one': 'One', 'a.two': 'Two' });
    const initial = await hashesOf(files);
    const [first, second] = await Promise.all([
      save(files, draft('a.one', '하나!', 'One!', '하나', 'One'), realOps, initial),
      save(files, draft('a.two', '둘!', 'Two!', '둘', 'Two'), realOps, initial),
    ]);
    expect(first.ok).toBe(true);
    expect(second.ok).toBe(false);
    if (!second.ok) expect(second.errors[0].code).toBe('conflict');
    const ko = JSON.parse(await readFile(files.koPath, 'utf8')) as Record<string, string>;
    const en = JSON.parse(await readFile(files.enPath, 'utf8')) as Record<string, string>;
    expect(ko['a.one']).toBe('하나!');
    expect(en['a.one']).toBe('One!');
  });

  test('test_10a_copy_save_returns_the_saved_values_after_a_stale_page', async () => {
    const files = await fixture({ 'a.one': '하나' }, { 'a.one': 'One' });
    const initial = await hashesOf(files);
    const first = await save(
      files,
      draft('a.one', '하나!', 'One', '하나', 'One'),
      realOps,
      initial,
    );
    expect(first).toMatchObject({ ok: true, ko: '하나!', en: 'One' });
    const second = await save(
      files,
      draft('a.one', '하나', 'One!', '하나', 'One'),
      realOps,
      initial,
    );
    expect(second.ok).toBe(false);
    if (!second.ok) {
      expect(second.errors[0].code).toBe('conflict');
      expect(second.ko).toBe('하나!');
      expect(second.en).toBe('One');
    }
    const current = await hashesOf(files);
    const retry = await save(
      files,
      draft('a.one', '하나!', 'One!', '하나!', 'One'),
      realOps,
      current,
    );
    expect(retry).toMatchObject({ ok: true, ko: '하나!', en: 'One!' });
    const ko = JSON.parse(await readFile(files.koPath, 'utf8')) as Record<string, string>;
    const en = JSON.parse(await readFile(files.enPath, 'utf8')) as Record<string, string>;
    expect(ko['a.one']).toBe('하나!');
    expect(en['a.one']).toBe('One!');
  });

  test('test_10a_copy_save_reports_a_conflict_when_the_same_language_changed', async () => {
    const files = await fixture({ 'a.one': '하나' }, { 'a.one': 'One' });
    expect(await save(files, draft('a.one', '하나!', 'One', '하나', 'One'))).toMatchObject({
      ok: true,
      ko: '하나!',
      en: 'One',
    });
    const second = await save(files, draft('a.one', '다른!', 'One', '하나', 'One'));
    expect(second.ok).toBe(false);
    if (!second.ok) expect(second.errors[0].code).toBe('conflict');
    const ko = JSON.parse(await readFile(files.koPath, 'utf8')) as Record<string, string>;
    expect(ko['a.one']).toBe('하나!');
  });

  test('test_10a_copy_save_restores_both_files_when_the_second_replace_fails', async () => {
    const files = await fixture({ 'a.one': '하나' }, { 'a.one': 'One' });
    const koBefore = await readFile(files.koPath, 'utf8');
    const enBefore = await readFile(files.enPath, 'utf8');
    const ops: CopyFileOps = {
      ...realOps,
      rename: async (from, to) => {
        if (to === files.enPath) throw new Error('the second replace fails');
        await realOps.rename(from, to);
      },
    };
    const result = await save(files, draft('a.one', '하나!', 'One!', '하나', 'One'), ops);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[0].code).toBe('write');
    expect(await readFile(files.koPath, 'utf8')).toBe(koBefore);
    expect(await readFile(files.enPath, 'utf8')).toBe(enBefore);
    const names = [...(await readdir(join(files.root, 'ko'))), ...(await readdir(join(files.root, 'en')))];
    expect(names.some((name) => name.includes('.copy-'))).toBe(false);
  });

  test('test_10a_copy_save_reports_a_partial_write_when_the_restore_fails', async () => {
    const files = await fixture({ 'a.one': '하나' }, { 'a.one': 'One' });
    let koRenames = 0;
    const ops: CopyFileOps = {
      ...realOps,
      rename: async (from, to) => {
        if (to === files.enPath) throw new Error('the second replace fails');
        if (to === files.koPath) {
          koRenames += 1;
          if (koRenames > 1) throw new Error('the restore fails');
        }
        await realOps.rename(from, to);
      },
    };
    const result = await save(files, draft('a.one', '하나!', 'One!', '하나', 'One'), ops);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[0].code).toBe('partial');
    const ko = JSON.parse(await readFile(files.koPath, 'utf8')) as Record<string, string>;
    const en = JSON.parse(await readFile(files.enPath, 'utf8')) as Record<string, string>;
    expect(ko['a.one']).toBe('하나!');
    expect(en['a.one']).toBe('One');
  });

  test('test_10a_copy_save_reports_a_conflict_when_a_file_changes_during_the_save', async () => {
    const files = await fixture({ 'a.one': '하나' }, { 'a.one': 'One' });
    let tampered = false;
    const ops: CopyFileOps = {
      ...realOps,
      writeFile: async (path, data, encoding) => {
        await realOps.writeFile(path, data, encoding);
        if (!tampered && path.startsWith(files.koPath) && path.endsWith('.tmp')) {
          tampered = true;
          await realOps.writeFile(
            files.koPath,
            `${JSON.stringify({ 'a.one': '다른 편집' }, null, 2)}\n`,
            'utf8',
          );
        }
      },
    };
    const result = await save(files, draft('a.one', '하나!', 'One!', '하나', 'One'), ops);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[0].code).toBe('conflict');
    const ko = JSON.parse(await readFile(files.koPath, 'utf8')) as Record<string, string>;
    expect(ko['a.one']).toBe('다른 편집');
    const names = [...(await readdir(join(files.root, 'ko'))), ...(await readdir(join(files.root, 'en')))];
    expect(names.some((name) => name.includes('.copy-'))).toBe(false);
  });

  test('test_10a_copy_save_removes_a_stale_lock_and_keeps_a_manual_edit', async () => {
    const files = await fixture({ 'a.one': '하나', 'a.two': '둘' }, { 'a.one': 'One', 'a.two': 'Two' });
    await mkdir(join(files.lockDir, 'copy-shell.lock'), { recursive: true });
    await writeFile(join(files.lockDir, 'copy-shell.lock', 'pid'), '2147483647', 'utf8');
    await writeFile(
      files.koPath,
      `${JSON.stringify({ 'a.one': '하나', 'a.two': '손으로 고침' }, null, 2)}\n`,
      'utf8',
    );
    const result = await save(files, draft('a.one', '하나!', 'One!', '하나', 'One'));
    expect(result).toMatchObject({ ok: true, ko: '하나!', en: 'One!' });
    const ko = JSON.parse(await readFile(files.koPath, 'utf8')) as Record<string, string>;
    expect(ko['a.two']).toBe('손으로 고침');
    expect(await readdir(files.lockDir)).toEqual([]);
  });

  test('test_10a_copy_save_rejects_an_empty_value_and_keeps_the_files', async () => {
    const files = await fixture({ 'a.one': '하나' }, { 'a.one': 'One' });
    const before = await readFile(files.koPath, 'utf8');
    const result = await save(files, draft('a.one', '', 'One', '하나', 'One'));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[0].code).toBe('empty-ko');
    expect(await readFile(files.koPath, 'utf8')).toBe(before);
  });

  test('test_10a_copy_save_rejects_a_missing_placeholder', async () => {
    const files = await fixture({ 'a.one': '파일 {name} 삭제' }, { 'a.one': 'Remove {name}' });
    const result = await save(files, draft('a.one', '파일 삭제', 'Remove {name}', '파일 {name} 삭제', 'Remove {name}'));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[0].code).toBe('placeholder-ko');
  });

  test('test_10a_copy_save_rejects_different_key_sets', async () => {
    const files = await fixture({ 'a.one': '하나', 'a.two': '둘' }, { 'a.one': 'One' });
    const result = await save(files, draft('a.one', '하나!', 'One!', '하나', 'One'));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.map((error) => error.code)).toContain('key-set');
  });

  test('test_10a_copy_save_rejects_an_unknown_key', async () => {
    const files = await fixture({ 'a.one': '하나' }, { 'a.one': 'One' });
    const result = await save(files, draft('a.missing', '하나', 'One', '하나', 'One'));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[0].code).toBe('unknown-key');
  });
});

describe('copy request body', () => {
  test('test_10a_copy_body_decodes_a_utf8_character_split_across_chunks', async () => {
    const stream = Readable.from([Buffer.from([0xea]), Buffer.from([0xb0, 0x80])]);
    expect(await readBody(stream)).toBe('가');
  });
});

describe('copy write guard', () => {
  const origins = approvedOrigins({ host: undefined, port: 4300, https: false });

  test('test_10a_copy_write_needs_local_edit_mode_and_an_approved_origin', () => {
    expect(isLoopback('127.0.0.1')).toBe(true);
    expect(isLoopback('100.64.0.2')).toBe(false);
    expect(origins).toContain('http://127.0.0.1:4300');
    expect(
      canWriteCopy({
        edit: true,
        remoteAddress: '127.0.0.1',
        origin: 'http://127.0.0.1:4300',
        host: '127.0.0.1:4300',
        approvedOrigins: origins,
      }),
    ).toBe(true);
    expect(
      canWriteCopy({
        edit: true,
        remoteAddress: '127.0.0.1',
        origin: 'https://127.0.0.1:4300',
        host: '127.0.0.1:4300',
        approvedOrigins: origins,
      }),
    ).toBe(false);
    expect(
      canWriteCopy({
        edit: true,
        remoteAddress: '127.0.0.1',
        origin: 'http://other.example:4300',
        host: 'other.example:4300',
        approvedOrigins: origins,
      }),
    ).toBe(false);
    expect(
      canWriteCopy({
        edit: true,
        remoteAddress: '127.0.0.1',
        origin: 'http://127.0.0.1:4300',
        host: 'other.example:4300',
        approvedOrigins: origins,
      }),
    ).toBe(false);
    expect(
      canWriteCopy({
        edit: false,
        remoteAddress: '127.0.0.1',
        origin: 'http://127.0.0.1:4300',
        host: '127.0.0.1:4300',
        approvedOrigins: origins,
      }),
    ).toBe(false);
    expect(
      canWriteCopy({
        edit: true,
        remoteAddress: '100.64.0.2',
        origin: 'http://127.0.0.1:4300',
        host: '127.0.0.1:4300',
        approvedOrigins: origins,
      }),
    ).toBe(false);
  });

  test('test_10a_copy_edit_flag_uses_the_same_origins', () => {
    expect(
      canEditCopy({
        edit: true,
        remoteAddress: '127.0.0.1',
        referer: 'http://127.0.0.1:4300/src/gallery/index.html?tab=copy',
        approvedOrigins: origins,
      }),
    ).toBe(true);
    expect(
      canEditCopy({
        edit: true,
        remoteAddress: '127.0.0.1',
        referer: 'http://other.example:4300/',
        approvedOrigins: origins,
      }),
    ).toBe(false);
    expect(
      canEditCopy({
        edit: true,
        remoteAddress: '127.0.0.1',
        referer: undefined,
        approvedOrigins: origins,
      }),
    ).toBe(false);
  });

  test('test_10a_copy_exposed_host_has_no_writable_origin', () => {
    expect(approvedOrigins({ host: true, port: 4300, https: false })).toEqual([]);
    expect(approvedOrigins({ host: '0.0.0.0', port: 4300, https: false })).toEqual([]);
    expect(approvedOrigins({ host: '100.64.0.2', port: 4300, https: false })).toEqual([]);
    expect(approvedOrigins({ host: 'localhost', port: 4300, https: true })).toContain(
      'https://localhost:4300',
    );
  });
});
